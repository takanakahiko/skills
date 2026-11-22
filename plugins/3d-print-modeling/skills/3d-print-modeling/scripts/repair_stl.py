# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = ["numpy", "scipy", "trimesh", "shapely", "triangle>=20250106", "networkx"]
# ///
"""印刷用 STL を水密（多様体）にする後処理。

JSCAD のブーリアン出力は、隣り合う三角形の辺の途中に別の三角形の頂点が乗る「T 字接合」を含み、
Bambu Studio では "open edges" として警告される。ここでは同一平面上でつながった三角形を 1 つの多角形にまとめ、
その境界線上に乗っている全頂点を境界に挿入してから三角形分割し直す。面と面の間で境界の頂点集合が一致するので
T 字接合が構造的に無くなる。

使い方: uv run repair_stl.py a.stl b.stl [--out dir]
（水密にできたファイルだけ書き出す。既定は上書き。水密にできなかったファイルは元のまま残す）
依存: numpy scipy trimesh shapely triangle networkx
"""
import glob, os, sys
import numpy as np
import trimesh
from shapely.geometry import Polygon
from scipy.spatial import cKDTree

MERGE_R = 0.02       # この距離以内の頂点は同一点として結合する [mm]（ブーリアン誤差による極薄の破片を潰す。最小肉厚 2mm より十分小さい）
FIN_W = 0.1          # 髪の毛状のヒレとみなす面の最小高さ [mm]
FIN_FOLD_DEG = 170   # 隣接面との折り返し角がこれ以上なら「折り返し」


def merge_pairs(mesh: trimesh.Trimesh, pairs, faces=None) -> trimesh.Trimesh:
    """頂点の組を union-find で結合し（直径 MERGE_R 超のクラスタは除外）、潰れた面を除去する"""
    V = mesh.vertices
    F = mesh.faces if faces is None else faces
    parent = np.arange(len(V))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b in pairs:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    root = np.array([find(i) for i in range(len(V))])
    # 連鎖して大きくなったクラスタ（細かい折れ線の頂点列など）は結合しない
    for rt in np.unique(root):
        idx = np.where(root == rt)[0]
        if len(idx) > 1 and np.ptp(V[idx], axis=0).max() > FIN_W:
            root[idx] = idx
    uniq, inv = np.unique(root, return_inverse=True)
    out = trimesh.Trimesh(vertices=V[uniq], faces=inv[F], process=False)
    out.update_faces(out.nondegenerate_faces())
    out.update_faces(out.unique_faces())
    return out


def merge_close_vertices(mesh: trimesh.Trimesh, r=MERGE_R) -> trimesh.Trimesh:
    """距離 r 以内の頂点を 1 点に結合する"""
    return merge_pairs(mesh, cKDTree(mesh.vertices).query_pairs(r))


def remove_fins(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """髪の毛状のヒレ（隣の面と 170° 以上折り返していて、高さ 0.1mm 未満の面）を削除し、
    その短い辺の両端を結合して両側の面を直接つなぐ"""
    V = mesh.vertices
    F = mesh.faces
    fold = mesh.face_adjacency[mesh.face_adjacency_angles > np.radians(FIN_FOLD_DEG)]
    if len(fold) == 0:
        return mesh
    cand = np.unique(fold.reshape(-1))
    T = V[F[cand]]
    e = np.stack([T[:, 1] - T[:, 0], T[:, 2] - T[:, 1], T[:, 0] - T[:, 2]], axis=1)
    L = np.linalg.norm(e, axis=2)
    area2 = np.linalg.norm(np.cross(e[:, 0], e[:, 1]), axis=1)
    height = area2 / np.maximum(L.max(axis=1), 1e-12)   # 最長辺に対する高さ
    fins = cand[height < FIN_W]
    if len(fins) == 0:
        return mesh
    keep = np.ones(len(F), dtype=bool)
    keep[fins] = False
    pairs = []
    for f in fins:
        for i in range(3):
            a, b = F[f][i], F[f][(i + 1) % 3]
            if np.linalg.norm(V[a] - V[b]) < FIN_W:
                pairs.append((int(a), int(b)))
    out = merge_pairs(mesh, pairs, faces=F[keep])
    print(f'   ヒレ状の面 {len(fins)} 枚を除去')
    return out


def plane_basis(normal):
    n = normal / np.linalg.norm(normal)
    a = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1.0, 0])
    u = np.cross(n, a); u /= np.linalg.norm(u)
    v = np.cross(n, u)
    return n, u, v


def boundary_loops(edges):
    """向き付きの境界辺 (a,b) の集合から閉ループを組み立てる"""
    nxt = {}
    for a, b in edges:
        nxt.setdefault(a, []).append(b)
    loops, used = [], set()
    for a, b in edges:
        if (a, b) in used:
            continue
        loop, cur = [a], b
        used.add((a, b))
        while cur != a and len(loop) < 100000:
            if cur in loop:
                # 同じ頂点を再訪（8 の字）: そこからの部分ループを独立したループとして切り出す
                k = loop.index(cur)
                sub, loop = loop[k:], loop[:k]
                if len(sub) >= 3:
                    loops.append(sub)
            loop.append(cur)
            cands = [c for c in nxt.get(cur, []) if (cur, c) not in used]
            if not cands:
                break
            c = cands[0]
            used.add((cur, c))
            cur = c
        if cur == a and len(loop) >= 3:
            loops.append(loop)
    return loops


LINE_TOL = 0.05         # 開いた辺の連鎖をたどるとき、辺 AB の直線から許す距離 [mm]
CHAIN_COS = np.cos(np.radians(3))  # 連鎖の各辺と AB の方向のずれの上限


def open_edge_graph(mesh):
    """開いた辺（面が 1 つしか付いていない辺）の無向グラフ: 頂点 → 隣接頂点の集合"""
    oe = mesh.edges[trimesh.grouping.group_rows(mesh.edges_sorted, require_count=1)]
    nb = {}
    for a, b in oe.tolist():
        nb.setdefault(a, set()).add(b)
        nb.setdefault(b, set()).add(a)
    open_set = {tuple(sorted(e)) for e in oe.tolist()}
    return nb, open_set


def chain_between(a, b, V, nb):
    """開いた辺を a から b へ向かって共線的にたどり、途中の頂点（T 字の頂点）を a→b の順で返す。
    たどり着けない場合は途中まで（両方向から集めて呼び出し側で統合する）"""
    A, B = V[a], V[b]
    d = B - A
    L = float(np.linalg.norm(d))
    if L < 1e-9:
        return []
    d /= L
    found = []
    cur, t_cur = a, 0.0
    for _ in range(10000):
        best = None
        for n in nb.get(cur, ()):
            if n == b:
                if cur == a:
                    continue  # AB そのもの（開いた辺）は無視する
                return found
            if n == a or n in found:
                continue
            P = V[n]
            t = float((P - A) @ d)
            if not (t_cur < t < L):
                continue
            if np.linalg.norm((P - A) - t * d) > LINE_TOL:
                continue
            step = P - V[cur]
            if float(step @ d) / max(np.linalg.norm(step), 1e-12) < CHAIN_COS:
                continue
            if best is None or t < best[1]:
                best = (n, t)
        if best is None:
            return found
        found.append(best[0])
        cur, t_cur = best
    return found


def insert_on_edge_vertices(loop, V, nb, open_set, exclude):
    """ループの各辺 AB について、元メッシュで AB が開いた辺なら、隣の面の頂点が AB 上に乗っている（T 字）ので
    開いた辺の連鎖 A→…→B をたどって、その頂点を順序を保って挿入する"""
    out = []
    n = len(loop)
    for i in range(n):
        a, b = loop[i], loop[(i + 1) % n]
        out.append(a)
        if tuple(sorted((a, b))) not in open_set:
            continue
        fwd = chain_between(a, b, V, nb)
        bwd = chain_between(b, a, V, nb)
        mids = [x for x in dict.fromkeys(fwd + bwd[::-1]) if x not in exclude]
        if mids:
            A = V[a]; d = V[b] - A
            mids.sort(key=lambda x: float((V[x] - A) @ d))
            out.extend(mids)
    return out


COPLANAR_ANGLE = 1e-4   # 同一平面とみなす法線の角度差 [rad]（trimesh の facets は数度の差も同一視するので使わない）
COPLANAR_DIST = 1e-3    # 同一平面とみなす平面オフセットの差 [mm]


def coplanar_groups(mesh: trimesh.Trimesh):
    """辺で隣接し、かつ厳密に同一平面にある面を連結成分ごとにまとめる"""
    N = mesh.face_normals
    C = mesh.triangles_center
    adj = mesh.face_adjacency
    same = (np.einsum('ij,ij->i', N[adj[:, 0]], N[adj[:, 1]]) > np.cos(COPLANAR_ANGLE)) & \
           (np.abs(np.einsum('ij,ij->i', C[adj[:, 1]] - C[adj[:, 0]], N[adj[:, 0]])) < COPLANAR_DIST)
    parent = np.arange(len(mesh.faces))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b in adj[same]:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
    root = np.array([find(i) for i in range(len(mesh.faces))])
    order = np.argsort(root, kind='stable')
    splits = np.flatnonzero(np.diff(root[order])) + 1
    return [list(g) for g in np.split(order, splits)]


def remesh(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    V = mesh.vertices
    F = mesh.faces
    groups = coplanar_groups(mesh)
    nb, open_set = open_edge_graph(mesh)
    new_faces = []
    fallback = 0
    for g in groups:
        faces = F[g]
        n, u, v = plane_basis(mesh.face_normals[g[0]])
        # グループの境界辺（グループ内で 1 回しか現れない向き付き辺）
        e = np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
        key = {}
        for a, b in map(tuple, e):
            key[(a, b)] = key.get((a, b), 0) + 1
        bnd = [(a, b) for (a, b), c in key.items() if c == 1 and (b, a) not in key]
        loops = boundary_loops(bnd)
        if not loops:
            new_faces.extend(faces.tolist()); fallback += 1
            continue
        present = {i for lp in loops for i in lp}
        loops = [insert_on_edge_vertices(lp, V, nb, open_set, present) for lp in loops]
        origin = V[loops[0][0]]
        to2d = lambda idx: np.column_stack([(V[idx] - origin) @ u, (V[idx] - origin) @ v])
        polys = []
        for lp in loops:
            p2 = to2d(np.array(lp))
            area = 0.5 * np.sum(p2[:, 0] * np.roll(p2[:, 1], -1) - np.roll(p2[:, 0], -1) * p2[:, 1])
            polys.append((lp, p2, area))
        outers = [p for p in polys if p[2] > 0]
        holes = [p for p in polys if p[2] < 0]
        ok = False
        for lp, p2, _ in outers:
            shell = Polygon(p2)
            inner = [(hl, h2) for hl, h2, _ in holes if shell.contains(Polygon(h2).representative_point())]
            try:
                poly = Polygon(p2, [h2 for _, h2 in inner])
                verts2d, tris = trimesh.creation.triangulate_polygon(poly, engine='triangle', triangle_args='pYYQ')
            except Exception:
                continue
            allidx = list(lp) + [i for hl, _ in inner for i in hl]
            all2d = np.vstack([p2] + [h2 for _, h2 in inner])
            mapping = []
            for q in verts2d:
                d = np.linalg.norm(all2d - q, axis=1)
                j = int(np.argmin(d))
                if d[j] > 1e-6:
                    mapping = None; break
                mapping.append(allidx[j])
            if mapping is None or len(tris) == 0:
                continue
            t = np.array(mapping)[tris]
            tri_n = np.cross(V[t[:, 1]] - V[t[:, 0]], V[t[:, 2]] - V[t[:, 0]])
            flip = (tri_n @ n) < 0
            t[flip] = t[flip][:, [0, 2, 1]]
            new_faces.extend(t.tolist())
            ok = True
        if not ok:
            new_faces.extend(faces.tolist()); fallback += 1
    out = trimesh.Trimesh(vertices=V.copy(), faces=np.array(new_faces), process=False)
    out.update_faces(out.nondegenerate_faces())
    out.update_faces(out.unique_faces())
    return out, fallback


def repair_file(src, dst=None):
    m = remove_fins(merge_close_vertices(trimesh.load(src, process=False)))
    v0, n0 = m.volume, len(m.faces)
    r, fb = remesh(m)
    bnd = len(trimesh.grouping.group_rows(r.edges_sorted, require_count=1))
    wt = r.is_watertight
    print(f'{os.path.basename(src):28s} 三角形 {n0} → {len(r.faces)}  体積 {v0/1000:.2f} → {r.volume/1000:.2f} cm3  '
          f'境界辺 {bnd}  未処理面 {fb}  ' + ('水密 OK' if wt else 'NG（出力しません）'))
    if wt:
        r.fix_normals()
        r.export(dst or src)
    return wt


def main():
    import argparse
    ap = argparse.ArgumentParser(description='STL の T 字接合・極薄破片を除去して水密化する')
    ap.add_argument('files', nargs='+', help='入力 STL（既定では上書き）')
    ap.add_argument('--out', help='出力ディレクトリ（指定すると上書きせずここに書く）')
    a = ap.parse_args()
    if a.out:
        os.makedirs(a.out, exist_ok=True)
    ok = True
    for f in a.files:
        ok &= repair_file(f, os.path.join(a.out, os.path.basename(f)) if a.out else None)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
