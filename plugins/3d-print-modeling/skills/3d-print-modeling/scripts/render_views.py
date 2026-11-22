# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = ["numpy", "trimesh", "matplotlib", "shapely", "scipy", "networkx"]
# ///
"""STL を画像にする。形の把握・お手本との比較・組み付け確認に使う。

使い方:
  uv run render_views.py a.stl [b.stl ...] --out views.png
      各ファイルを別パネルに、アイソメ 2 方向 + 上面 + 正面で描く（お手本と結果を同じ視点で並べる用途）
  uv run render_views.py a.stl b.stl --overlay --out assembled.png
      全ファイルを同じ座標系に重ねて描く（組み付け確認）。色は順に橙・灰・緑・青
  uv run render_views.py a.stl --sections z=2,6,10 x=5 --out sec.png
      指定平面での断面輪郭を描く（--overlay と併用すると重ねた断面になる）
  --translate "b.stl=0,9,6.28" でファイルごとに平行移動できる（組み付け位置に置く）
"""
import argparse, os
import numpy as np, trimesh
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

COLORS = ["#ff8800", "#9aa0aa", "#55aa55", "#3366cc", "#cc3366", "#aa8833"]


def draw3d(ax, meshes, el, az, title):
    lo = np.min([m.bounds[0] for m, _ in meshes], axis=0); hi = np.max([m.bounds[1] for m, _ in meshes], axis=0)
    c = (lo + hi) / 2; r = (hi - lo).max() / 2 * 1.05
    for m, col in meshes:
        ax.add_collection3d(Poly3DCollection(m.vertices[m.faces], facecolor=col, edgecolor="#00000018", lw=0.1))
    ax.set_xlim(c[0]-r, c[0]+r); ax.set_ylim(c[1]-r, c[1]+r); ax.set_zlim(c[2]-r, c[2]+r)
    ax.view_init(el, az); ax.set_title(title, fontsize=9); ax.set_xlabel("x"); ax.set_ylabel("y"); ax.set_zlabel("z")


def draw_section(ax, meshes, axis, v):
    ai = "xyz".index(axis); oth = [i for i in range(3) if i != ai]
    o = np.zeros(3); o[ai] = v; n = np.zeros(3); n[ai] = 1
    for m, col in meshes:
        s = m.section(plane_origin=o, plane_normal=n)
        if s is None: continue
        for e in s.entities:
            pts = s.vertices[e.points]; ax.plot(pts[:, oth[0]], pts[:, oth[1]], color=col, lw=1.2)
    ax.set_aspect("equal"); ax.grid(True, lw=0.3); ax.set_title(f"{axis}={v}", fontsize=9)
    ax.set_xlabel("xyz"[oth[0]]); ax.set_ylabel("xyz"[oth[1]])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--overlay", action="store_true")
    ap.add_argument("--sections", nargs="*", default=[], help="例: z=2,6,10 x=5")
    ap.add_argument("--translate", nargs="*", default=[], help="例: b.stl=0,9,6.28")
    a = ap.parse_args()
    tr = {}
    for t in a.translate:
        k, v = t.split("="); tr[k] = [float(x) for x in v.split(",")]
    meshes = []
    for i, f in enumerate(a.files):
        m = trimesh.load(f)
        if f in tr: m.apply_translation(tr[f])
        meshes.append((m, COLORS[i % len(COLORS)]))
    secs = []
    for s in a.sections:
        axis, vals = s.split("="); secs += [(axis, float(v)) for v in vals.split(",")]
    views = [(30, -60, "iso"), (30, 120, "iso back"), (90, -90, "top"), (0, -90, "front")]

    if a.overlay:
        n3 = 0 if secs else len(views)
        cols = max(n3 + len(secs), 1)
        fig = plt.figure(figsize=(4.5 * cols, 4.8))
        for i, (el, az, t) in enumerate(views[:n3]):
            draw3d(fig.add_subplot(1, cols, i + 1, projection="3d"), meshes, el, az, t)
        for j, (axis, v) in enumerate(secs):
            draw_section(fig.add_subplot(1, cols, n3 + j + 1), meshes, axis, v)
        if secs and n3 == 0 and len(secs) == 1:
            pass
    else:
        rows = len(meshes); cols = len(views) if not secs else len(secs)
        fig = plt.figure(figsize=(4.5 * cols, 4.5 * rows))
        for r, (m, col) in enumerate(meshes):
            if secs:
                for j, (axis, v) in enumerate(secs):
                    draw_section(fig.add_subplot(rows, cols, r * cols + j + 1), [(m, col)], axis, v)
            else:
                for i, (el, az, t) in enumerate(views):
                    draw3d(fig.add_subplot(rows, cols, r * cols + i + 1, projection="3d"), [(m, col)], el, az,
                           f"{os.path.basename(a.files[r])} {t}  {np.round(m.extents, 1)}")
    fig.tight_layout(); fig.savefig(a.out, dpi=80)
    print("書き出し:", a.out)


if __name__ == "__main__":
    main()
