# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = ["numpy", "trimesh", "scipy", "networkx"]
# ///
"""3MF（Bambu Studio / MakerWorld 形式を含む）から部品ごとの STL・寸法・付属画像・印刷設定を取り出す。

お手本のモデルを渡されたとき、最初に実行して「何が何個、どんな寸法で、どう印刷する設定か」を把握するためのもの。

使い方: uv run extract_3mf.py model.3mf [--out dir]
出力: dir/<部品名>.stl（原点を bounding box の最小角に移動済み）、dir/images/*.png（webp は macOS の sips で変換）、
      標準出力に部品一覧（名前・個数・寸法・三角形数・水密）、タイトル・作者・説明の冒頭、主要な印刷設定
"""
import argparse, json, os, re, shutil, subprocess, sys, zipfile
import numpy as np, trimesh


def parse_mesh(xml: str):
    v = np.array(re.findall(r'<vertex x="([-\d.eE+]+)" y="([-\d.eE+]+)" z="([-\d.eE+]+)"', xml), float)
    f = np.array(re.findall(r'<triangle v1="(\d+)" v2="(\d+)" v3="(\d+)"', xml), int)
    return v, f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--out", help="出力ディレクトリ（既定: <3mf 名>_extracted）")
    a = ap.parse_args()
    out = a.out or os.path.splitext(os.path.basename(a.path))[0] + "_extracted"
    os.makedirs(out, exist_ok=True)
    z = zipfile.ZipFile(a.path)
    names = z.namelist()
    root = z.read("3D/3dmodel.model").decode("utf-8", "replace")

    # メタデータ
    meta = dict(re.findall(r'<metadata name="([^"]+)">([^<]*)', root))
    for k in ["Title", "Designer", "Application", "CreationDate", "License"]:
        if k in meta: print(f"{k}: {meta[k]}")
    if "Description" in meta:
        import html
        desc = meta["Description"]
        for _ in range(3): desc = html.unescape(desc)      # 多重エスケープされている
        desc = re.sub(r"<[^>]+>", " ", desc)
        print("Description:", re.sub(r"\s+", " ", desc)[:600])

    # 部品名: model_settings.config の <object id=ROOT> の name。ROOT は 3dmodel.model の <object id=ROOT> で、
    # その <component p:path=... objectid=MESH> がメッシュを指す（Bambu 形式）。メッシュがルートに直接ある形式にも対応
    root_names = {}
    if "Metadata/model_settings.config" in names:
        ms = z.read("Metadata/model_settings.config").decode("utf-8", "replace")
        for m in re.finditer(r'<object id="(\d+)">\s*<metadata key="name" value="([^"]+)"', ms):
            root_names[m.group(1)] = m.group(2)
    obj_names, refs = {}, {}   # (path, meshid) → name / 参照回数（= プレート上の個数）
    built = set(re.findall(r'<item objectid="(\d+)"', root))
    for m in re.finditer(r'<object id="(\d+)"[^>]*>(.*?)</object>', root, re.S):
        rid, body = m.group(1), m.group(2)
        n = 1 if (rid in built or not built) else 0
        for c in re.finditer(r'<component [^>]*?p:path="([^"]+)"[^>]*?objectid="(\d+)"', body):
            key = (c.group(1).lstrip("/"), c.group(2))
            obj_names[key] = root_names.get(rid, f"object_{rid}"); refs[key] = refs.get(key, 0) + n
        if "<vertex" in body:
            key = ("3D/3dmodel.model", rid)
            obj_names[key] = root_names.get(rid, f"object_{rid}"); refs[key] = refs.get(key, 0) + n

    # メッシュ: ルートに直接あるか、3D/Objects/*.model に分かれているか
    meshes = {}   # (path, meshid) → (v, f)
    for n in ["3D/3dmodel.model"] + [n for n in names if n.startswith("3D/Objects/") and n.endswith(".model")]:
        xml = root if n == "3D/3dmodel.model" else z.read(n).decode("utf-8", "replace")
        for m in re.finditer(r'<object id="(\d+)"[^>]*>(.*?)</object>', xml, re.S):
            v, f = parse_mesh(m.group(2))
            if len(f): meshes[(n, m.group(1))] = (v, f)
    if not meshes:
        sys.exit("メッシュが見つからない")

    # 同名の部品は 1 つだけ書き出し、個数を数える
    seen, counts = {}, {}
    for key, (v, f) in meshes.items():
        name = obj_names.get(key, f"object_{key[1]}")
        base = re.sub(r"\.(stl|3mf|obj)$", "", name, flags=re.I)
        counts[base] = counts.get(base, 0) + max(refs.get(key, 1), 1)
        if base in seen: continue
        m = trimesh.Trimesh(v, f); m.apply_translation(-m.bounds[0])
        p = os.path.join(out, re.sub(r"[^\w.+-]+", "_", base) + ".stl")
        m.export(p); seen[base] = (p, m)
    print("\n部品一覧:")
    for base, (p, m) in sorted(seen.items(), key=lambda kv: -kv[1][1].volume):
        print(f"  {base:40s} x{counts[base]:<3d} 寸法 {np.round(m.extents, 2)} 三角形 {len(m.faces):6d} 水密 {m.is_watertight}  → {p}")

    # 印刷設定
    if "Metadata/project_settings.config" in names:
        try:
            c = json.loads(z.read("Metadata/project_settings.config"))
            keys = ["printer_settings_id", "print_settings_id", "filament_settings_id", "filament_type", "layer_height",
                    "wall_loops", "sparse_infill_density", "enable_support", "support_type", "elefant_foot_compensation", "curr_bed_type"]
            print("\n印刷設定:", {k: c.get(k) for k in keys if k in c})
        except Exception as e:
            print("印刷設定の読み取り失敗:", e)

    # 画像
    imgs = [n for n in names if re.search(r"\.(png|jpe?g|webp)$", n, re.I) and not n.startswith("Metadata/")]
    if imgs:
        d = os.path.join(out, "images"); os.makedirs(d, exist_ok=True)
        for n in imgs:
            dst = os.path.join(d, os.path.basename(n))
            with open(dst, "wb") as fh: fh.write(z.read(n))
            if dst.lower().endswith(".webp") and shutil.which("sips"):
                png = os.path.splitext(dst)[0] + ".png"
                if subprocess.run(["sips", "-s", "format", "png", dst, "--out", png], capture_output=True).returncode == 0:
                    os.remove(dst)
        print(f"\n画像 {len(imgs)} 枚 → {d}（Read ツールで見る。組み付け写真があれば取り付け向きの根拠になる）")


if __name__ == "__main__":
    main()
