# 機票日期規劃

依「國家／地區、旅遊天數、假日、請假天數」找出最划算的出發日期組合，再一鍵開啟帶好條件的 Google Flights 查即時價格。網頁放在 GitHub Pages，不需要註冊任何 API、沒有金鑰。

## 第一次設定

1. **開啟 GitHub Pages**：Settings → Pages → Source 選「Deploy from a branch」，Branch 選 `main`、資料夾選 `/docs`，按 Save。
2. **產生假日資料**：Actions → 「更新假日資料」→ Run workflow（年份空白 = 今年與明年）。
3. 打開 `https://sleeping35.github.io/flight-price-tracker/` 即可使用。

之後每年 7/1、12/1 會自動檢查人事總處是否公告了新年度的辦公日曆。

## 使用方式

- **出發地／目的地**：目的地可選單一地區（每個機場各一個查價按鈕），或整個國家（一個按鈕，交給 Google Flights 搜尋全國機場）。
- **假日模式**
  - 含週末：行程包含完整的週六與週日。
  - 含國定連假：行程包含整段連假（連續 3 天以上放假，且其中有平日放假）。
  - 最少請假：依「連休天數 ÷ 請假天數」由高到低排序。
- **請假天數**：去程到回程之間的上班日（含補班日）。勾選「去回程日算半天假」時，去程日與回程日若是上班日只算 0.5 天。
- **連休天數**：行程本身，加上緊接在去程前、回程後的放假日。
- 尚未公告辦公日曆的年份只用週六日判斷，結果會標示「假日未公告」。
- 篩選條件會寫進網址，可以直接加書籤。

## 降價通知

在 Google Flights 的查詢結果頁打開「追蹤價格」（需要登入 Google 帳號），價格變動時 Google 會寄 email 通知。

## 新增國家或地區

直接在 GitHub 網站上編輯 `config/regions.yaml`（檔案開頭有格式說明）並 commit 到 `main`。「更新地區清單」workflow 會自動產生網頁用的 `docs/data/regions.json`，格式有誤時該 workflow 會失敗並顯示原因。

## 資料夾

| 路徑 | 內容 |
| --- | --- |
| `config/regions.yaml` | 地區對照表：國家 → 地區 → 機場代碼 |
| `tracker/` | Python 小工具：產生 regions.json、下載假日資料（在 GitHub Actions 執行） |
| `docs/` | GitHub Pages 網頁 |
| `docs/data/holidays/` | 行政機關辦公日曆（含補班日），每年一個 JSON |

## 本機開發

```bash
pip install -r requirements.txt pytest
python -m pytest
```

## 之後想要自動抓價

如果之後想要價格歷史與走勢圖，可以再註冊 Travelpayouts（免費）並加回每日抓價的 workflow。這個 repo 的第一個 PR 歷史裡有完整的抓價程式可以參考。
