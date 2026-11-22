# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = ["numpy", "trimesh", "shapely", "matplotlib", "scipy", "networkx", "manifold3d"]
# ///
"""押し出し形状のモデルを「寸法だけ変えて」作り直す。形はいじらない。

断面（平面で切った 2D 輪郭）を取り、直線部分だけを伸縮させて押し出す。角の丸め・爪・フックなど
伸縮区間の外にある形はそのまま残る。お手本を別サイズの相手に合わせるときに使う。

使い方:
  uv run stretch_profile.py src.stl --plane z=4 --depth 8 \
      --x-keep 3,11 --dx 2.2  --y-keep 5,13.5 --dy 4.5  --out out.stl [--plot before_after.png]
  --plane   断面を取る平面。押し出し方向の軸と位置（例 z=4 なら z 軸方向に押し出された形）
  --x-keep  断面 2D 座標の x について、この範囲の内側だけを伸縮する（外側は形を保ったまま平行移動）
  --dx      その伸縮量（正で伸ばす、負で縮める）。y も同様
  --depth   押し出し長さ。省略時は元の長さ
  --drop    断面にある小さな穴や別片を捨てる面積のしきい値（既定 0.05 mm^2）
断面 2D 座標は、平面の法線以外の 2 軸を元の順（z 平面なら x,y、y 平面なら x,z、x 平面なら y,z）で使う。
"""
import argparse, sys
import numpy as np, trimesh
from shapely.geometry import Polygon
from shapely.ops import transform, unary_union


def remap(v, lo, hi, d):
    if v <= lo: return v
    if v >= hi: return v + d
    return lo + (v - lo) * (hi + d - lo) / (hi - lo)


def section_polygon(m, axis, val, drop):
    ai = "xyz".index(axis); oth = [i for i in range(3) if i != ai]
    o = np.zeros(3); o[ai] = val; n = np.zeros(3); n[ai] = 1
    s = m.section(plane_origin=o, plane_normal=n)
    polys = []
    for path in s.discrete:
        pts = np.asarray(path)[:, oth]
        if len(pts) >= 3:
            p = Polygon(pts).buffer(0)
            if p.area > drop: polys.append(p)
    polys.sort(key=lambda p: p.area, reverse=True)
    outer = polys[0]
    holes = [p for p in polys[1:] if outer.contains(p.representative_point())]
    return Polygon(outer.exterior.coords, [h.exterior.coords for h in holes]), oth


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("--plane", required=True); ap.add_argument("--depth", type=float)
    ap.add_argument("--x-keep", default=None); ap.add_argument("--dx", type=float, default=0.0)
    ap.add_argument("--y-keep", default=None); ap.add_argument("--dy", type=float, default=0.0)
    ap.add_argument("--drop", type=float, default=0.05)
    ap.add_argument("--out", required=True); ap.add_argument("--plot")
    a = ap.parse_args()
    axis, val = a.plane.split("="); val = float(val)
    m = trimesh.load(a.src)
    src, oth = section_polygon(m, axis, val, a.drop)
    xk = [float(v) for v in a.x_keep.split(",")] if a.x_keep else [np.inf, np.inf]
    yk = [float(v) for v in a.y_keep.split(",")] if a.y_keep else [np.inf, np.inf]
    f = lambda x, y, z=None: (remap(x, xk[0], xk[1], a.dx), remap(y, yk[0], yk[1], a.dy))
    dst = transform(f, src)
    if dst.geom_type != "Polygon":
        sys.exit(f"伸縮後の断面が {dst.geom_type} になった（伸縮区間が形状の細部にかかっている）")
    depth = a.depth or m.extents["xyz".index(axis)]
    out = trimesh.creation.extrude_polygon(dst, depth)     # 押し出し軸は z
    # 断面 2D (u, v) = (oth[0], oth[1]) と押し出し軸 axis を元の軸順に戻す
    T = np.zeros((4, 4)); T[3, 3] = 1
    T[oth[0], 0] = 1; T[oth[1], 1] = 1; T["xyz".index(axis), 2] = 1
    out.apply_transform(T); out.fix_normals(); out.apply_translation(-out.bounds[0])
    out.export(a.out)
    print(f"断面 bounds {np.round(src.bounds, 2)} → {np.round(dst.bounds, 2)}  穴 {len(src.interiors)} → {len(dst.interiors)}")
    print(f"書き出し: {a.out} 外形 {np.round(out.extents, 2)} 水密 {out.is_watertight}")
    if a.plot:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        fig, axes = plt.subplots(1, 2, figsize=(14, 9))
        for ax, p, t in [(axes[0], src, "before"), (axes[1], dst, "after")]:
            ax.set_aspect("equal"); ax.grid(True, lw=0.3); ax.set_title(t)
            ax.plot(*p.exterior.xy, "b-")
            for h in p.interiors: ax.plot(*h.xy, "b-")
        fig.tight_layout(); fig.savefig(a.plot, dpi=80); print("比較図:", a.plot)


if __name__ == "__main__":
    main()
