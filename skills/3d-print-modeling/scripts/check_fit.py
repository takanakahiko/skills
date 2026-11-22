# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = ["numpy", "trimesh", "manifold3d", "rtree", "scipy", "networkx", "shapely"]
# ///
"""部品と相手部品の干渉体積・最短距離を計算する。可動する相手は回転させた姿勢も並べて調べる。

使い方:
  uv run check_fit.py part.stl mate1.stl [mate2.stl ...]
  uv run check_fit.py part.stl --spec spec.json
spec.json の例（相手部品ごとの配置。rotate は軸・角度・回転中心）:
  [
    {"file": "chain.stl", "label": "chain"},
    {"file": "lid.stl",   "translate": [0, 9, 6.28]},
    {"file": "chain.stl", "translate": [0, -20, 0], "rotate": {"axis": [1,0,0], "deg": 30, "origin": [0,6,6]}, "label": "prev+30"}
  ]
--print-orientation を付けると part.stl の印刷向きも確認する（設置面の面積が断面と一致するか、45° 超の下向き面があるか）。
干渉が 0.001 mm^3 以上の相手があれば終了コード 1。
最短距離が設計した隙間と一致することも確認する（0 に近すぎれば接触、想定より大きければ位置ずれ）。
"""
import argparse, json, os, sys
import numpy as np, trimesh


def load_spec(a):
    items = []
    if a.spec:
        for it in json.load(open(a.spec)):
            m = trimesh.load(it["file"])
            if "translate" in it: m.apply_translation(it["translate"])
            if "rotate" in it:
                r = it["rotate"]
                m.apply_transform(trimesh.transformations.rotation_matrix(np.radians(r["deg"]), r["axis"], r.get("origin", [0, 0, 0])))
            items.append((it.get("label", os.path.basename(it["file"])), m))
    for f in a.mates:
        items.append((os.path.basename(f), trimesh.load(f)))
    return items


def print_orientation(m):
    fn = m.face_normals
    z0 = np.all(np.abs(m.vertices[m.faces][:, :, 2] - m.bounds[0][2]) < 1e-6, axis=1)
    bottom = m.area_faces[z0 & (fn[:, 2] < -0.99)].sum()
    over = m.area_faces[(fn[:, 2] < -0.707) & ~z0].sum()
    print(f"印刷向き: 設置面 {bottom:.1f} mm^2, 設置面以外の 45° 超の下向き面 {over:.1f} mm^2（0 ならサポート不要）, 外形 {np.round(m.extents, 2)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("part")
    ap.add_argument("mates", nargs="*")
    ap.add_argument("--spec")
    ap.add_argument("--print-orientation", action="store_true")
    a = ap.parse_args()
    part = trimesh.load(a.part)
    print(f"{os.path.basename(a.part)}: 外形 {np.round(part.extents, 2)} 水密 {part.is_watertight}")
    ok = True
    for label, m in load_spec(a):
        inter = trimesh.boolean.intersection([part, m], engine="manifold")
        v = 0.0 if inter.is_empty else abs(inter.volume)
        d = min(trimesh.proximity.closest_point(m, part.vertices)[1].min(), trimesh.proximity.closest_point(part, m.vertices)[1].min())
        flag = "OK" if v < 1e-3 else "NG"
        if v >= 1e-3: ok = False
        print(f"  {label:16s} 干渉 {v:8.3f} mm^3 {flag}  最短距離 {d:6.3f} mm")
    if a.print_orientation: print_orientation(part)
    if not ok:
        print("干渉あり", file=sys.stderr); sys.exit(1)


if __name__ == "__main__":
    main()
