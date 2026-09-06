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

- 特定の得点数を固定の成功条件にしない
- 更新前の得点合計は比較用の参考値として扱い、更新後の成功条件には固定しない
- 更新後は `python tests/verify_2026_rankings.py` の結果を正とする
- 検証時点の `event_goals = rank_all_goals = team_all_goals` が一致
- ALL / DIV1 / DIV2 で個人合計とチーム合計が一致
- 2026年9月時点では218点であり、以後の正式な更新によって変動しうる
- 過去の194点は当時の確認済み値であり、将来更新後の固定条件ではない
- 得点合計または区分別合計が不一致の場合はHOLDまたはFAIL
- VERDICT=PASS
