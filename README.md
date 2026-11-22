# skills

takanakahiko が自分用に作った Claude Code のスキル集です。スキルごとに 1 つのプラグインになっているので、必要なものだけを入れられます。

| プラグイン | 内容 |
|---|---|
| `retro-blog` | エージェントの視点で書く振り返りブログ（ISUCON などの記録）の書き方と図の指針 |
| `review-branch-diff` | 現在のブランチの差分を、事実確認したうえで批判的にレビューする |
| `3d-print-modeling` | FDM 3D プリント用モデルをコードで生成・検査・修復する知識とスクリプト |
| `bambu-studio-3mf` | STL から Bambu Studio でそのまま開けるプロジェクト 3MF を作る |

## インストール

Claude Code の場合:

```
/plugin marketplace add takanakahiko/skills
/plugin install retro-blog@takanakahiko
```

ほかのエージェントの場合は、skills CLI でも入れられます:

```
npx skills add takanakahiko/skills
```

## ライセンス

MIT
