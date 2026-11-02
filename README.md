# 機票價格追蹤

每天在 GitHub Actions 上抓取台北出發的機票價格，存成 JSON，並在 GitHub Pages 網頁上依「國家／地區、旅遊天數、假日、請假天數」篩選與排序。網頁上不放任何 API 金鑰；要確認即時價格時，點「確認」開啟帶好條件的 Google Flights。

## 第一次設定

1. **申請 API 金鑰**
   - Travelpayouts：到 <https://www.travelpayouts.com> 註冊（免費），在 Profile → API token 取得 token。
   - SerpApi：到 <https://serpapi.com> 註冊免費方案（每月 250 次），在 Dashboard 取得 API key。
2. **把金鑰放進 Secrets**：repo 的 Settings → Secrets and variables → Actions → New repository secret
   - `TRAVELPAYOUTS_TOKEN`
   - `SERPAPI_KEY`
3. **開啟 GitHub Pages**：Settings → Pages → Source 選「Deploy from a branch」，Branch 選 `main`、資料夾選 `/docs`。
4. **產生假日資料**：Actions → 「更新假日資料」→ Run workflow（年份空白 = 今年與明年）。
5. **測試覆蓋率**：Actions → 「抓取機票價格」→ Run workflow，勾選「覆蓋率測試」。在 log 裡可以看到每個航線拿到幾筆資料，這一步不會寫檔。
6. **正式抓價**：同一個 workflow 不勾選測試再執行一次。完成後打開 Pages 網址即可使用。

之後每天台灣時間 06:17 會自動執行。

## 新增航線或國家

1. 在 `config/regions.yaml` 加上國家／地區與機場代碼（檔案開頭有說明）。
2. 在 `config/watchlist.yaml` 的 `watches` 加上地區 key。
3. push 後到 Actions 手動執行「抓取機票價格」，可以在 `region` 欄位填新地區 key，只抓那一區。

Travelpayouts 沒有資料的航線，可以在 watchlist 裡對該地區加上 `source: serpapi` 改用 SerpApi（每月額度有限，程式到 230 次會自動停）。

## 資料夾

| 路徑 | 內容 |
| --- | --- |
| `config/` | 追蹤清單、地區對照表 |
| `tracker/` | Python 抓價程式（`python -m tracker fetch`） |
| `tracker/sources/` | 資料來源模組，統一介面 `FareSource` |
| `docs/` | GitHub Pages 網頁 |
| `docs/data/latest.json` | 目前各日期組合的最低價 |
| `docs/data/history/` | 每日價格紀錄（第二版畫走勢圖用），保留 24 個月 |
| `docs/data/holidays/` | 行政機關辦公日曆（含補班日） |
| `docs/data/usage.json` | 每月 API 用量 |

## 網頁的假日計算

- **含週末**：行程包含完整的週六與週日。
- **含國定連假**：行程包含整段連假（連續 3 天以上放假，且其中有平日放假）。
- **請假天數**：去程到回程之間的上班日（含補班日）。勾選「去回程日算半天假」時，去程日與回程日若是上班日只算 0.5 天。
- **連休天數**：行程本身，加上緊接在去程前、回程後的放假日。
- **最少請假**：依「連休天數 ÷ 請假天數」由高到低排序。
- 尚未公告辦公日曆的年份，只用週六日判斷，結果會標示「假日未公告」。

## 本機開發

公司電腦不需要能連外部 API，只需要能跑測試：

```bash
pip install -r requirements.txt pytest
python -m pytest
```

## 注意

- 公開 repo 若 60 天沒有任何活動，GitHub 會自動停用排程。每日抓價的 commit 通常就算活動；若在 Actions 頁面看到排程被停用的提示，按「Enable workflow」即可恢復。
- 金鑰只透過環境變數傳入程式，送出請求前後印出的訊息都會遮蔽金鑰。
