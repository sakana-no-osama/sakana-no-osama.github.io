# 検証とプレビューの使い方

## 保存データから確認する

Windows PowerShellでプロジェクトを開き、次を実行する。

```powershell
.\tools\build_preview.ps1
```

Pythonが使える環境では次も同じ処理になる。作業フォルダに依存せず、プロジェクトのdataを参照する。

```text
python -B tools/build_preview.py
```

3種類のデータ検証、HTML内の表とCSVの一致、チーム詳細用データの一致を確認し、`.preview/index.html`と`.preview/manifest.json`を生成する。Web取得、正式CSVの変更、index.htmlの上書き、Git操作は行わない。

入力CSV・コード・運用文書と出力HTMLのSHA-256が前回のPASS時と一致する場合は再生成を省く。HTMLを手編集した場合や入力が変わった場合は再検証する。必ず再検証するにはPowerShellで`-Force`、Pythonで`--force`を指定する。

プレビューのPASSは「保存データとの整合」を意味する。最新試合の取得済み、未確認の予定が解消済み、公開承認済みを意味しない。2025_D2_m31の未確認1点は既存ルールどおり維持する。

## 正確性の改善

- ランキングは総得点だけでなく、選手名・チーム名・得点・順位・得点試合数・最多得点者・注記まで全行を照合する。
- 開催済みCSVが試合マスターのplayed行の正確な抽出になっていることを確認する。
- 得点イベントの重複、試合ID・日付・区分の不一致、各チームのスコアとの不一致を検出する。
- 検証失敗は終了コード1、取得処理のHOLDは終了コード2で返す。
- 取得・解析に失敗した際は旧CSVを維持する。書き込みは同一フォルダの一時ファイルを完成させた後に置き換える。

2026年10月2日の更新では、公式の部別一覧と開催済み全試合の詳細を照合し、予定行を再取得した。取得結果にreview行が残る場合はHOLDとなるため、公式情報の構造を確認してから更新する。会場だけが公式に未掲載の場合は空欄と`venue_not_published`を保存し、画面に「公式情報に未掲載」と表示する。

延期試合が一覧の先頭にあっても、次節は未開催試合の開催日順で選ぶ。公式の節名と「各部4試合・8チーム」の確認は維持する。

## 取得した公式HTMLから更新候補を作る

`tools/prepare_2026_update.py`は、保存した`div1.html`・`div2.html`と開催済み試合の`2026_D1_m01.html`形式の詳細HTMLを読み、新しい空フォルダへ候補CSVを生成する。公式データへの上書きや通信は行わない。既存試合の結果・得点者が変わっていた場合はHOLDとする。使用したHTMLのSHA-256を候補フォルダの親の`update_report.json`へ記録する。

```text
python -B tools/prepare_2026_update.py --raw-dir <取得HTMLフォルダ> --output-dir <空の候補フォルダ> --as-of 2026-10-02
python -B tests/verify_2026_rankings.py --data-dir <候補フォルダ>
python -B tests/verify_2026_standings_fixtures.py --data-dir <候補フォルダ>
python -B tests/verify_2026_match_scorers.py --data-dir <候補フォルダ>
python -B scripts/build_all_years_ranking_html.py --data-dir <候補フォルダ> --output <候補HTML>
```

日付は確認日へ置き換える。候補生成だけでは公開可能とは判定せず、3検証・CSV差分・画面確認を行ってから運用ルールに従って反映する。

## ファイルの役割と出力先

- `scripts/ranking_checks.py`: 取得・生成処理から独立したデータ照合。
- `scripts/preview_checks.py`: HTMLの表・カード・チーム詳細データの照合。
- `scripts/workflow_io.py`: プロジェクトの基準パスと安全なファイル置換。
- `web/ranking.css`、`web/ranking.js`: 表示・検索・操作。生成HTML内に埋め込むため追加通信は不要。
- `tests/test_workflow_safety.py`: 一時コピーと通信モックで検証する回帰テスト。
- `scripts/official_division.py`: 公式の部別一覧に明記された日付・チーム・スコアの解析。
- `tests/test_official_sources.py`: 延期日程、未掲載会場、公式ページの不正な構造の回帰テスト。

2026年の試合・得点イベント生成は、引数なしで`data/`を使う。入力CSVを明示した場合は、出力指定がなければ入力CSVと同じフォルダへ出力する。

個人・チームランキング生成は、第1引数が入力CSV、第2引数が出力フォルダ（省略時は入力CSVの親フォルダ）。通常運用では候補フォルダに生成し、3検証と差分確認を経て反映する。

```text
python -B scripts/build_goal_ranking_2026.py data/goal_events_2026.csv <候補フォルダ>
python -B scripts/build_team_ranking_2026.py data/goal_events_2026.csv <候補フォルダ>
python -B -m unittest discover -s tests -p "test_*.py" -v
```

2025年用・旧Termux用スクリプトの入出力仕様は変更していない。次節カード生成の「各部4試合」条件も残るため、節の途中やシーズン終了時の扱いは別途改善が必要。

## 画面の変更

- 全角・半角・空白を吸収した検索。次節カードも検索対象に含める。
- 表示件数、検索解除、該当なしメッセージを表示する。
- チーム内順位はそのチームの得点順で計算する。同点は同順位にする。
- キーボードでチーム詳細を開ける。Escapeで閉じる。
- 収録試合の最終日とページ生成日時を分ける。過去日付の予定には未反映の注意を表示し、公式ページにリンクする。
- 「試合数」は意味を明確にするため「得点試合」と表示する（順位表の出場試合数とは異なる）。

公開は引き続き`CODEX_UPDATE_RULES.md`の手順に従う。プレビュー確認後のローカルindex.html反映と、mainへのmerge・pushは別工程。
