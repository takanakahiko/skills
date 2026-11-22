#!/usr/bin/env python3
"""STL から Bambu Studio プロジェクト 3MF を作る（標準ライブラリのみ、python3 で直接実行できる）。

使い方:
  python3 bambu_3mf.py model.stl --out model.3mf \
      [--printer "Bambu Lab A1 mini 0.4 nozzle"] [--process "0.20mm Standard @BBL A1M"] \
      [--filament "Bambu PETG Basic @BBL A1M 0.4 nozzle"] [--set enable_support=0 ...] [--bed "Textured PEI Plate"]
複数の STL を渡せば同じプレートに並べる。
"""
import argparse, json, os, shutil, subprocess, sys, tempfile, zipfile

APP = "/Applications/BambuStudio.app/Contents/MacOS/BambuStudio"
PROFILES = "/Applications/BambuStudio.app/Contents/Resources/profiles/BBL"


def load_preset(kind, name):
    p = os.path.join(PROFILES, kind, name + ".json")
    if not os.path.exists(p):
        cands = [f[:-5] for f in os.listdir(os.path.join(PROFILES, kind)) if name.split("@")[0].strip().lower() in f.lower()][:10]
        sys.exit(f"プリセットが無い: {p}\n候補: {cands}")
    return json.load(open(p))


def flatten(kind, name):
    """inherits を根まで辿ってマージ（子が優先）。CLI は 1 段しか解決しないため"""
    chain, cur = [], name
    while cur:
        d = load_preset(kind, cur); chain.append(d); cur = d.get("inherits")
    merged = {}
    for d in reversed(chain):
        # machine の開始/終了 G-code などは include 先の別ファイルにある。CLI は include を解決しない
        for inc in d.get("include", []):
            merged.update({k: v for k, v in load_preset(kind, inc).items() if k not in ("name", "instantiation")})
        merged.update(d)
    for k in ("inherits", "setting_id", "include"): merged.pop(k, None)
    return merged


def flat_machine(printer, td):
    """継承と include を展開したプリンタ設定を書き出す。
    ユーザープリセットとして渡し、inherits に元のシステムプリセット名を残す（互換判定がこれを見る）"""
    m = flatten("machine", printer)
    m.update({"from": "User", "instantiation": "true", "inherits": printer})
    path = os.path.join(td, "machine.json")
    json.dump(m, open(path, "w"))
    return path


META = {"name", "from", "inherits", "setting_id", "instantiation", "compatible_printers", "compatible_printers_condition",
        "compatible_prints", "compatible_prints_condition", "print_settings_id", "filament_settings_id", "printer_settings_id",
        "type", "filament_id", "version", "include", "description"}


def _same(a, b):
    """書式違い（"100" と "100%"、"1.0" と "1"、CLI が詰めたリスト長）を同一とみなす"""
    if isinstance(a, list) or isinstance(b, list):
        a = a if isinstance(a, list) else [a]; b = b if isinstance(b, list) else [b]
        return all(_same(x, y) for x, y in zip(a, b))
    norm = lambda v: str(v).strip().rstrip("%").replace("x", ",")
    x, y = norm(a), norm(b)
    try:
        return float(x) == float(y)
    except ValueError:
        return x == y


def use_system_presets(path, printer, process, filaments, overrides=()):
    """CLI 用に付けた (custom)/(flat) の名前を元のシステムプリセット名に戻す。
    そのままだと Bambu Studio で開いたときに「プロジェクトプリセット」が作られる。
    overrides（--set で変えたキー）だけをシステムとの差分として残し、GUI では「変更あり」のシステムプリセットに見せる。
    それ以外で CLI が勝手に変えた値（例: A1 mini の最大加速度が 6000 に下がる）はシステム値に戻す"""
    # フィラメントの差分判定は 1 本目を基準にする（フィラメント別の配列値は 1 本目の値と比べる）
    sysv = {"process": flatten("process", process), "filament": flatten("filament", filaments[0]), "machine": flatten("machine", printer)}
    owner = {}  # キーの持ち主: フィラメント > プロセス > プリンタ（共通の基底に重複して載っているキーがある）
    for kind in ("machine", "process", "filament"):
        for k in sysv[kind]: owner[k] = kind
    tmp = path + ".tmp"
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "Metadata/project_settings.config":
                cfg = json.loads(data)
                diffs = {"process": [], "filament": [], "machine": []}
                n_fil = len(filaments)
                for k, kind in owner.items():
                    if k in META or k not in cfg: continue
                    if kind == "filament" and n_fil > 1: continue  # 複数本のときはフィラメント設定（色など）をそのまま残す
                    if _same(cfg[k], sysv[kind][k]): continue
                    if k in overrides: diffs[kind].append(k)
                    else: cfg[k] = sysv[kind][k]
                cfg["print_settings_id"] = process
                cfg["filament_settings_id"] = list(filaments)
                cfg["printer_settings_id"] = printer
                cfg["inherits_group"] = [""] * (n_fil + 2)
                cfg["different_settings_to_system"] = (
                    [";".join(sorted(diffs["process"]))] + [";".join(sorted(diffs["filament"]))] * n_fil + [";".join(sorted(diffs["machine"]))])
                cfg.pop("inherits", None)
                data = json.dumps(cfg, indent=4, ensure_ascii=False).encode()
            zout.writestr(item, data)
    shutil.move(tmp, path)


def set_bed_type(path, bed):
    tmp = path + ".tmp"
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "Metadata/project_settings.config":
                cfg = json.loads(data); cfg["curr_bed_type"] = bed
                data = json.dumps(cfg, indent=4, ensure_ascii=False).encode()
            zout.writestr(item, data)
    shutil.move(tmp, path)


def reset_item_rotation(path, cx=90.0, cy=90.0):
    """CLI は物体を勝手に回して置くことがある（180° 回ってフィギュアが奥を向いた）。
    STL の向きのまま、外形の中心がプレートの (cx, cy) に来るよう配置の変換を書き直す。
    部品の変換は中心基準の頂点を元の座標へ戻す平行移動なので、その値が外形の中心になる"""
    import re
    tmp = path + ".tmp"
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "3D/3dmodel.model":
                s = data.decode()
                comps = re.findall(r'<component [^>]*transform="1 0 0 0 1 0 0 0 1 ([-\d.e]+) ([-\d.e]+) [-\d.e]+"', s)
                items = re.findall(r'<item [^>]*transform="([^"]+)"', s)
                if len(comps) == 1 and len(items) == 1:  # 物体が 1 つのときだけ直す
                    ox, oy = map(float, comps[0])
                    new = f'transform="1 0 0 0 1 0 0 0 1 {cx - ox:.6f} {cy - oy:.6f} 0"'
                    if items[0].split()[:9] != "1 0 0 0 1 0 0 0 1".split():
                        print("配置の回転を戻した:", items[0], "->", new)
                    s = re.sub(r'(<item [^>]*?)transform="[^"]*"', lambda m: m.group(1) + new, s)
                    data = s.encode()
            zout.writestr(item, data)
    shutil.move(tmp, path)


def center_components(path, cx=90.0, cy=90.0):
    """--load-assemble-list の pos は外形の最小角として扱われ、中心がプレート外へずれる。
    各物体のメッシュは原点中心なので、component の平行移動を (cx, cy) にそろえる（item 側のプレート間オフセットは残す）"""
    import re
    tmp = path + ".tmp"
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "3D/3dmodel.model":
                s = re.sub(r'(<component [^>]*transform="1 0 0 0 1 0 0 0 1 )[-\d.e]+ [-\d.e]+( [-\d.e]+")',
                           lambda m: f"{m.group(1)}{cx:.6f} {cy:.6f}{m.group(2)}", data.decode())
                data = s.encode()
            zout.writestr(item, data)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stl", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--printer", default="Bambu Lab A1 mini 0.4 nozzle")
    ap.add_argument("--process", default="0.20mm Standard @BBL A1M")
    ap.add_argument("--filament", action="append", default=[],
                    help="フィラメントのプリセット名。複数回指定すると AMS のスロット順に 1, 2, ... になる（既定 Bambu PETG Basic）")
    ap.add_argument("--colour", action="append", default=[], help="フィラメントの色 #RRGGBB（--filament と同じ順）")
    ap.add_argument("--set", action="append", default=[], help="プロセス設定の上書き key=value")
    ap.add_argument("--bed", default="Textured PEI Plate")
    ap.add_argument("--one-per-plate", action="store_true", help="STL ごとに別プレートに置く（ベッドに並ばない大物向け）")
    a = ap.parse_args()
    a.filament = a.filament or ["Bambu PETG Basic @BBL A1M 0.4 nozzle"]
    out_dir = os.path.abspath(os.path.dirname(a.out)) or os.getcwd()
    os.makedirs(out_dir, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        fps = []
        for i, name in enumerate(a.filament):
            fil = flatten("filament", name)
            fil.update({"from": "User", "name": f"{name} (flat{i + 1})", "filament_settings_id": [f"{name} (flat{i + 1})"],
                        "compatible_printers": [a.printer], "instantiation": "true"})
            if i < len(a.colour): fil["filament_colour"] = [a.colour[i]]
            fil.pop("filament_id", None)
            fps.append(os.path.join(td, f"filament{i + 1}.json"))
            json.dump(fil, open(fps[-1], "w"))
        proc = flatten("process", a.process)
        for kv in a.set:
            k, v = kv.split("=", 1); proc[k] = v
        pname = a.process + " (custom)" if a.set else a.process + " (flat)"
        proc.update({"from": "User", "name": pname, "print_settings_id": pname,
                     "compatible_printers": [a.printer], "instantiation": "true"})
        pp = os.path.join(td, "process.json")
        json.dump(proc, open(pp, "w"))
        machine = flat_machine(a.printer, td)
        cmd = [APP, "--load-settings", f"{machine};{pp}", "--load-filaments", ";".join(fps),
               "--export-3mf", os.path.basename(a.out), "--outputdir", out_dir, "--debug", "1"]
        if a.one_per_plate:
            # --load-assemble-list は STL 引数と併用できない。pos は外形の中心をプレート中央に置く
            plates = []
            for i, s in enumerate(a.stl):
                plates.append({"plate_name": os.path.splitext(os.path.basename(s))[0], "need_arrange": False,
                               "objects": [{"path": os.path.abspath(s), "count": 1, "filaments": [1], "assemble_index": [i],
                                            "pos_x": [90.0], "pos_y": [90.0], "pos_z": [0.0]}]})
            al = os.path.join(td, "assemble.json")
            json.dump({"plates": plates}, open(al, "w"))
            cmd += ["--load-assemble-list", al]
        else:
            cmd += [os.path.abspath(s) for s in a.stl]
        r = subprocess.run(cmd, capture_output=True, text=True)
        rj = os.path.join(out_dir, "result.json")
        res = json.load(open(rj)) if os.path.exists(rj) else {"return_code": r.returncode, "error_string": r.stdout[-500:]}
        if os.path.exists(rj): os.remove(rj)
        if res.get("return_code") != 0:
            sys.exit(f"Bambu Studio CLI 失敗: {res.get('error_string')}\n{r.stdout[-1500:]}")
    out = os.path.join(out_dir, os.path.basename(a.out))
    set_bed_type(out, a.bed)
    if a.one_per_plate:
        center_components(out)
    else:
        reset_item_rotation(out)
    use_system_presets(out, a.printer, a.process, a.filament, [kv.split('=', 1)[0] for kv in a.set])
    with zipfile.ZipFile(out) as z:
        c = json.loads(z.read("Metadata/project_settings.config"))
    keys = ["printer_settings_id", "print_settings_id", "filament_settings_id", "filament_type", "filament_colour", "nozzle_temperature",
            "hot_plate_temp", "textured_plate_temp", "layer_height", "wall_loops", "sparse_infill_density", "enable_support",
            "support_filament", "support_interface_filament", "enable_prime_tower", "wipe_tower_x", "wipe_tower_y",
            "elefant_foot_compensation", "curr_bed_type"]
    print("書き出し:", out)
    print("設定確認:", {k: c.get(k) for k in keys})
    print("システムとの差分:", c.get("different_settings_to_system"))
    check_gcode(c)


def check_gcode(c):
    """開始 G-code が汎用の仮のもの（G28 だけ）になっていないか。include が落ちるとこうなる"""
    sg = c.get("machine_start_gcode", "")
    if len(sg) < 1000:
        sys.exit(f"machine_start_gcode が短すぎる（{len(sg)} 文字）。プリンタ設定の include が展開されていない: {sg[:80]!r}")
    print(f"開始 G-code: {len(sg)} 文字（OK）")


if __name__ == "__main__":
    main()
