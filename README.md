# skills

takanakahiko が作ったエージェント向けのスキル集です。どのスキルも `skills/<名前>/SKILL.md` に置いた標準の形式なので、Claude Code 以外のエージェントでも使えます。必要なものだけを入れられます。

| スキル | 内容 |
|---|---|
| `retro-blog` | エージェントの視点で書く振り返りブログ（ISUCON などの記録）の書き方と図の指針 |
| `review-branch-diff` | 現在のブランチの差分を、事実確認したうえで批判的にレビューする |
| `3d-print-modeling` | FDM 3D プリント用モデルをコードで生成・検査・修復する知識とスクリプト |
| `bambu-studio-3mf` | STL から Bambu Studio でそのまま開けるプロジェクト 3MF を作る |

## インストール

skills CLI（Claude Code、Codex、Cursor などに対応）:

```
npx skills add takanakahiko/skills                 # 選んで入れる
npx skills add takanakahiko/skills -s retro-blog   # 1 つだけ入れる
```

GitHub CLI（`--pin` でコミットやタグに固定できます）:

```
gh skill install takanakahiko/skills retro-blog --agent claude-code --scope user
```

## スキルを追加するとき

`skills/<名前>/SKILL.md` を置くだけです。

## ライセンス

MIT
