---
name: bambu-studio-3mf
description: STL から Bambu Studio でそのまま開いてスライスできるプロジェクト 3MF（プリンタ・プロセス・フィラメント設定込み）を作る。Bambu Studio CLI の癖（プリセット継承の未解決、プロジェクト設定の拒否、ベッド種別の未対応）への対処を含む。3D プリント用モデルの納品時に使う
---

# Bambu Studio プロジェクト 3MF の生成

3D プリント用モデルを納品するときは STL だけでなく、印刷向き・設定込みの 3MF を必ず添える（ユーザーの明示的な要望）。

## ツール

`scripts/bambu_3mf.py model.stl --out model.3mf [--printer ...] [--process ...] [--filament ...] [--set key=value ...] [--bed ...]`

- 既定は A1 mini 0.4 ノズル / 0.20mm Standard @BBL A1M / Bambu PETG Basic @BBL A1M 0.4 nozzle / Textured PEI Plate
- `--set enable_support=0 --set sparse_infill_density=20% --set wall_loops=3 --set elefant_foot_compensation=0.15` のようにプロセス設定を上書き
- プリセット名は `/Applications/BambuStudio.app/Contents/Resources/profiles/BBL/{machine,process,filament}/*.json` のファイル名（拡張子なし）
- STL は印刷向き（底面が z=0）にしておく。CLI は置き直しをしない
- 生成後に 3MF 内の `Metadata/project_settings.config` を読んで、filament_type・温度・support・bed が意図どおりか確認する

## CLI の癖（調べて分かったこと）

- `--load-settings` に 3MF から取り出した `project_settings.config` を渡すと「from project unsupported」で拒否される。プリセット形式（`type`・`name`・`from`・`compatible_printers` 付き JSON）でないと読まない
- プリセットの `inherits` は 1 段しか解決しない。内蔵フィラメント（例 PETG @A1M 0.4 → @base → fdm_filament_pet → common）をそのまま渡すと、素材が PLA 扱い・ベッド温度 45℃ のまま出る。継承チェーンを自前で平坦化して `from: "User"` の単一 JSON にして渡す（スクリプトがやる）
- ユーザープリセットには `compatible_printers` にプリンタ名が必要。無いと「process not compatible with printer」
- プリンタ設定の開始/終了 G-code・レイヤー変更 G-code などは `include` 先の別ファイル（`... template machine_start_gcode.json` 等）にあり、CLI は `include` を解決しない。システムのプリンタ JSON をそのまま渡すと `G28` だけの汎用開始 G-code が 3MF に入り、ベッドレベリング・パージ・ノズル拭きが抜ける（スライスは成功するので気付きにくい）。継承と include を展開して `from: "User"`・`inherits: <元のプリンタ名>` の JSON で渡す（inherits が無いと互換エラー）。スクリプトは生成後に開始 G-code の長さを検査する
- CLI に渡すプリセットは `(custom)` 等の別名のユーザープリセットなので、そのままだと GUI で開いたときに「プロジェクトプリセット」が作られる。書き出し後に `project_settings.config` の `*_settings_id` をシステム名に戻し、`--set` したキーだけを `different_settings_to_system`（[プロセス, フィラメント…, プリンタ] の `;` 区切り）に載せる。CLI は A1 mini の最大加速度を 6000 に下げるなど勝手に値を変えるので、意図しない差分はシステム値に戻す（書式違い "100"/"100%" は同一扱い）
- 1 プレートに並ばない複数部品はスクリプトの `--one-per-plate`（STL ごとに別プレート、中心をプレート中央にそろえる）
- 複数プレートは `--load-assemble-list a.json`（`pos_x/pos_y` は外形の中心ではなく最小角として扱われ、そのままだとプレート外にはみ出す）（`{"plates":[{"plate_name","need_arrange","objects":[{"path","count","filaments","assemble_index","pos_x","pos_y","pos_z"}]}]}`）。STL の引数とは併用不可
- 結果は出力ディレクトリの `result.json`（`return_code`・`error_string`）に出る。標準出力はログだけなので、成否は result.json で判定する
- CLI は物体を勝手に回して置くことがある（同じ形でも頂点を少し動かしただけで約 180° 回り、フィギュアがプレートの奥を向いた）。3MF の `3D/3dmodel.model` の `<item transform>` が配置。スクリプトは物体が 1 つのとき、回転なし・外形の中心がプレートの (90, 90)（A1 mini の中央）に来るよう書き直す。G-code と STL の座標を突き合わせるときも、この変換で戻す
- ベッド種別（`curr_bed_type`）は CLI から指定できない。3MF を zip として開き `Metadata/project_settings.config` を書き換える
- 内蔵プロセスの `elefant_foot_compensation` は A1 mini で 0。はめあい部品なら 0.15 程度を明示する
- 実行ファイルは `/Applications/BambuStudio.app/Contents/MacOS/BambuStudio`。`--help` で全オプションが見られる
