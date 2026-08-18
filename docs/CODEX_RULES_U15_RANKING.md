# 関東U-15女子 得点ランキング Codex運用ルール

## 最重要ルール

- 自動補完禁止
- 元データにない選手名、チーム名、得点、日付、試合結果を追加しない
- 不明点は HOLD として止める
- 0-0試合などの goals=0 診断行は goal_events CSV には残してよい
- goals=0 行はランキング集計から除外する
- goals>0 の行で team または player が空欄なら HOLD
- GitHub Pages公開前に必ず検証する
- git add . 禁止
- 公開反映は原則 index.html のみ
- 既存のバックアップや未追跡ファイルを削除しない

## 現在の既知問題

2026_D2_m26 は 0-0 試合。
goal_events_2026.csv に以下のような診断行がある。

team=''
player=''
goals=0
note='scorers_block_not_found'

この行は goal_events_2026.csv には残してよい。
ただしランキング集計からは除外する。

## 成功条件

- goal_events_2026.csv の得点合計 = 194
- goal_ranking_2026_all.csv の得点合計 = 194
- team_ranking_2026_all.csv の得点合計 = 194
- ALL / DIV1 / DIV2 で個人合計とチーム合計が一致
- VERDICT=PASS
