# 台北—大阪機票追蹤

每天早上 06:37（台灣時間）由 GitHub Actions 自動查詢 2027/4/1–4/26 出發、5 天 4 夜的桃園 TPE ⇄ 關西 KIX 直飛機票（2 大 1 小、經濟艙），存下結果，好價時推播 Telegram，並更新手機網頁。

## 檔案

| 位置 | 內容 |
| --- | --- |
| `config.json` | 所有設定：開關 `enabled`、目標價 `target_price`、連假日期、Ignav 額度與是否允許付費 |
| `tracker/` | 查價程式（`sources.py` 資料來源、`run.py` 每日流程、`notify.py` Telegram） |
| `data/daily.csv` | 每天每個出發日的最便宜組合總價 |
| `data/flights.csv` | 每天每個去程／回程日期前 3 便宜的航班 |
| `data/state.json` | 程式狀態（Ignav 已用次數、連續失敗天數等） |
| `docs/` | 網頁 app（GitHub Pages），`docs/data.json` 由每日排程產生 |
| `.github/workflows/daily.yml` | 每日排程 |

## 常用操作

- **暫停追蹤（買票後）**：把 `config.json` 的 `"enabled"` 改成 `false`。資料與網頁保留。
- **設定目標價**：把 `"target_price"` 改成數字，例如 `30000`（2 大 1 小來回總價，新台幣）。
- **行李估算**：`checked_bags`（托運件數，目前 2）與 `lcc_bag_fee`（每件每段估算費用，目前 NT$1,000，依虎航 tigersmart 與 tigerlight 差價）。廉航價格會加上「件數 × 費用」，網頁排名與週報、目標價都用含行李價格；新低價通知仍用原始票價。
- **允許 Ignav 付費**：免費 1,000 次用完後會暫停備援並通知；同意付費才把 `"ignav_allow_paid"` 改成 `true`。
- **手動執行／測試 Telegram**：Actions → 每日查價 → Run workflow，勾選「順便送一則 Telegram 測試訊息」。

## 需要的 GitHub Secrets

`TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`、`IGNAV_API_KEY`（Settings → Secrets and variables → Actions）。

## 本機試跑

```
pip install -r requirements.txt
python -m tracker.run --fake   # 用隨機價格試跑，不連網
```
