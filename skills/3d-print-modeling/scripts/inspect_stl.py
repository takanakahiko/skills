# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = ["numpy", "scipy", "trimesh", "networkx"]
# ///
"""STL が 3D プリントに耐えるかを数値で検査する。

使い方: uv run inspect_stl.py a.stl [b.stl ...] [--bed 180 180 180]
判定: 水密・巻き方向整合・開いた辺 0・非多様体辺 0・連結成分 1・ベッド内。どれか外れると終了コード 1
"""
import argparse, collections, os, sys
import numpy as np
import trimesh


def inspect(path, bed=None):
    m = trimesh.load(path)  # 既定の読み込みで同一座標の頂点を結合する（スライサーと同じ扱い）。process=False では判定できない
    g = collections.Counter(map(tuple, m.edges_sorted.tolist()))
    open_e = sum(1 for c in g.values() if c == 1)
    nonman = sum(1 for c in g.values() if c > 2)
    comps = len(m.split(only_watertight=False))
    ext = np.round(m.extents, 1)
    fits = bed is None or all(v <= b for v, b in zip(sorted(m.extents), sorted(bed)))
    ok = m.is_watertight and m.is_winding_consistent and open_e == 0 and nonman == 0 and comps == 1 and fits
    print(f"{os.path.basename(path):28s} 水密 {'OK' if m.is_watertight else 'NG':2s} 巻き {'OK' if m.is_winding_consistent else 'NG':2s} "
          f"開いた辺 {open_e:5d} 非多様体辺 {nonman:4d} 塊 {comps:3d} 体積 {m.volume/1000:8.2f} cm3 外形 {ext.tolist()} "
          f"{'' if fits else 'ベッド超過 '}{'OK' if ok else 'NG'}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='+')
    ap.add_argument('--bed', nargs=3, type=float, metavar=('X', 'Y', 'Z'), help='ベッド寸法 [mm]。向きは問わず、寸法をソートして比較')
    a = ap.parse_args()
    ok = all([inspect(f, a.bed) for f in a.files])
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
