# recall573-daily

大手自動車メーカーの NHTSA Part 573 Safety Recall Report（573届出）を毎朝更新して表示する PWA。

- 公開URL: https://superduperohiolife-lgtm.github.io/recall573-daily/
- 更新: GitHub Actions で毎朝 05:23 JST（予備 06:43 JST）。GitHub の定時実行は混雑時に遅延・スキップがあるため2回設定
- 手動更新: Actions → *Daily build & deploy* → *Run workflow*

## 表示仕様

- 一覧: 573 レポートに記載の提出日（Submission Date）で過去14日分を降順表示。改訂版（Amendment）も1件として並べる
- 明細: 不具合名 / MY・機種名 / 対象部品 / 台数 / 市場発生状況 / クロノロジー / 修理手法（すべて573原文の抜粋、要約なし）
- 改訂版: 直前の版との差分を表示（追加=緑、削除=赤の取り消し線、変更なしの項目は折りたたみ）。直前の版が NHTSA 未公開の場合は差分なし
- 単語タップ和訳: 英検2級相当（CEFR B1）以上の語のみ。CEFR-J で A1/A2 の語は対象外。自動車用語は `scripts/glossary.tsv` の訳を優先

## 対象メーカー

Toyota, Honda（二輪含む）, Nissan, Mazda, Subaru, Mitsubishi, GM, Ford, Stellantis, Hyundai, Kia, Genesis, VW Group, BMW, Mercedes-Benz, Tesla, Volvo（乗用車のみ。Honda 以外の二輪は除外）。
判定は `scripts/build.py` の `MAKERS`（NHTSA の manufacturer 表記に対する正規表現）。

## 構成

| パス | 内容 |
|---|---|
| `scripts/build.py` | NHTSA API 取得 → 573 PDF 解析 → 差分 → `site/data/*.json` 出力 |
| `scripts/glossary.tsv` | 自動車用語の和訳（辞書より優先） |
| `site/` | PWA 本体（静的。GitHub Pages で配信） |
| `.github/workflows/daily.yml` | 定時実行と Pages デプロイ |

## ローカル実行

```bash
sudo apt-get install poppler-utils
git clone --depth 1 https://github.com/kujirahand/EJDict.git .ext/EJDict
git clone --depth 1 https://github.com/openlanguageprofiles/olp-en-cefrj.git .ext/olp-en-cefrj
python3 scripts/build.py
cd site && python3 -m http.server
```

## データ出典

- NHTSA Part 573 Safety Recall Reports（api.nhtsa.gov / static.nhtsa.gov）
- 英和辞書: EJDict（パブリックドメイン）
- 語彙レベル: The CEFR-J Wordlist Version 1.5, compiled by Yukio Tono, Tokyo University of Foreign Studies. / Octanove Vocabulary Profile C1/C2（CC BY-SA 4.0）
