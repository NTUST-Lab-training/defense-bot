# Defense-Bot API 規格文件

* **Base URL**: `http://localhost:8088`
* **API Prefix**: `/api/v1`
* **互動式文件**: `http://localhost:8088/docs` (Swagger UI)

---

##  全域身分驗證機制 (Authentication)
為了落實「零信任架構 (Zero-Trust)」，所有前端專屬 API 皆不從 Request Body 接收學號，而是必須在 HTTP Header 帶上學生身分憑證（模擬登入狀態）：
* **Header Name**: `x-student-id`
* **Type**: `string`
* **Example**: `M11402165`

> **注意**：三支 Dify Agent 專用 Tool API 不依賴此 Header，而是由 Agent 在 Request Body 中傳入 `student_id` 參數。

---

##  前端專屬 API (Frontend RESTful)

### 1. 健康檢查 (Health Check)
* **Endpoint**: `GET /`
* **Auth Required**: **No**
* **說明**: 確認後端服務是否正常運作。
* **Response**:
```json
{
  "status": "running",
  "message": "Defense-Bot Backend is up and running!"
}
```

### 2. 取得個人首頁資訊 (Get My Profile)
* **Endpoint**: `GET /api/v1/students/me`
* **Auth Required**: **Yes** (`x-student-id` in Header)
* **說明**: 取得當前登入學生的基本資料與指導教授，供前端 Dashboard 畫面渲染使用。
* **Response**:
```json
{
  "student_id": "M11402165",
  "student_name": "趙祈佑",
  "thesis_title_zh": "智慧口試佈告生成系統",
  "thesis_title_en": "Defense-Bot",
  "advisor": "呂政修 教授 臺灣科技大學電子工程系"
}
```

### 3. 取得歷史口試紀錄 (Get My History)
* **Endpoint**: `GET /api/v1/defense/history`
* **Auth Required**: **Yes** (`x-student-id` in Header)
* **說明**: 取得該學生過去生成的所有口試佈告草稿與下載連結，供前端實作「歷史紀錄儀表板」。回傳結果依建立時間降冪排序。
* **Response**:
```json
[
  {
    "log_id": 1,
    "created_at": "2026-02-26T14:30:00",
    "defense_date": "民國115年3月4日(星期三)",
    "location": "第二教學大樓 T2-202會議室",
    "download_url": "http://127.0.0.1:8088/downloads/defense_M11402165_1.pptx"
  }
]
```

### 4. 對話代理 (Chat Proxy to Dify Agent)
* **Endpoint**: `POST /api/v1/chat`
* **Auth Required**: **Yes** (`x-student-id` in Header)
* **說明**: 前端對話的核心入口。後端會自動注入當前學生的姓名、論文題目與當前日期作為 Dify Agent 的 `inputs`，並以 Streaming 模式接收 Dify 回應後組裝為完整文字回傳。同時維護 `conversation_id` 以延續多輪對話記憶。
* **Request Body**:
```json
{
  "query": "下週五下午三點在 T2-202，委員是鄭瑞光和吳晉賢",
  "conversation_id": ""
}
```
| 欄位 | 型別 | 說明 |
|------|------|------|
| `query` | `string` (必填) | 使用者的自然語言訊息 |
| `conversation_id` | `string` (選填) | Dify 回傳的對話 ID，用於多輪對話延續，首次對話留空 |

* **Response**:
```json
{
  "answer": "好的，我已為您查詢地點「第二教學大樓 T2-202會議室」...",
  "conversation_id": "abc123-def456"
}
```

---

##  Dify Agent 專用 Tool API (ReAct 工作流)
以下三支 API 供 Dify Agent 在 ReAct 推理過程中主動呼叫，逐步完成地點驗證、委員糾錯與最終生成。

### 5. Tool 1：查詢與驗證地點 (Query Location)
* **Endpoint**: `POST /api/v1/tool/query_location`
* **Auth Required**: **No** (Dify Agent 直接呼叫)
* **說明**: 接收使用者輸入的地點關鍵字，依序執行以下邏輯：
  1. **精確命中**：資料庫模糊比對找到唯一結果 → 直接回傳補全後的完整地點名稱。
  2. **多筆候選**：找到多個匹配 → 回傳至多 3 筆建議，請 Agent 向使用者確認。
  3. **查無結果**：回傳整份全校地點名冊 (`reference_locations`)，讓 LLM 發揮諧音糾錯能力自行比對。
* **Request Body**:
```json
{
  "keyword": "T2-202"
}
```
* **Response (精確命中)**:
```json
{
  "status": "success",
  "full_location_name": "第二教學大樓 T2-202會議室",
  "suggestions": null,
  "message": null,
  "reference_locations": []
}
```
* **Response (查無結果 → 啟動諧音糾錯模式)**:
```json
{
  "status": "not_found",
  "full_location_name": null,
  "suggestions": null,
  "message": "資料庫直接比對查無「T2-999」。請啟動諧音糾錯模式，比對 reference_locations。",
  "reference_locations": ["電資館 EE-703-1 實驗室", "國際大樓 IB-201 會議室", "..."]
}
```

### 6. Tool 2：查詢與糾錯委員名單 (Query Committee)
* **Endpoint**: `POST /api/v1/tool/query_committee`
* **Auth Required**: **No** (Dify Agent 直接呼叫)
* **說明**: 接收學生學號與粗略的委員名字清單，執行以下防禦性邏輯：
  1. 以 `difflib.get_close_matches` (cutoff=0.6) 進行模糊比對，自動糾錯並補全職稱與系所。
  2. 偵測名字中含有「系」「所」「公司」等關鍵字的外部委員，保留原字串不比對。
  3. **強制自動補入指導教授**（即使使用者未提及）。
  4. 回傳 `unmatched_names`（完全無法匹配的名字）與 `reference_roster`（全校教授名冊），讓 LLM 自行進行第二輪諧音糾錯。
  5. 回傳 `is_valid_count` 旗標，標示委員人數是否已達到 3 人門檻。
* **Request Body**:
```json
{
  "student_id": "M11402165",
  "members": "鄭瑞洸、吳晉賢"
}
```
* **Response**:
```json
{
  "status": "success",
  "final_committee": [
    "鄭瑞光 教授 (臺灣科技大學電子工程系)",
    "吳晉賢 教授 (臺灣科技大學電子工程系)",
    "呂政修 教授 (臺灣科技大學電子工程系)"
  ],
  "unmatched_names": [],
  "reference_roster": [
    "呂政修 教授 (臺灣科技大學電子工程系)",
    "鄭瑞光 教授 (臺灣科技大學電子工程系)",
    "..."
  ],
  "is_valid_count": true,
  "current_count": 3
}
```

### 7. Tool 3：最終儲存並生成 PPT (Submit & Generate)
* **Endpoint**: `POST /api/v1/tool/submit_and_generate`
* **Auth Required**: **No** (Dify Agent 直接呼叫)
* **說明**: Agent 確認所有資料無誤後，一次性執行以下操作：
  1. 將西元日期自動轉換為民國年格式（含星期），例如 `2026-03-04` → `民國115年3月4日(星期三)`。
  2. 將最終結果寫入 `DefenseLog` 資料表。
  3. 呼叫 `python-pptx` 生成引擎，讀取 `templates/defense_template.pptx` 模板並替換佔位符。
  4. 回傳靜態檔案下載連結。
* **Request Body**:
```json
{
  "student_id": "M11402165",
  "defense_date": "2026-03-04",
  "defense_time": "14:00",
  "final_location": "第二教學大樓 T2-202會議室",
  "final_committee_str": "鄭瑞光 教授 (臺灣科技大學電子工程系), 吳晉賢 教授 (臺灣科技大學電子工程系), 呂政修 教授 (臺灣科技大學電子工程系)"
}
```
| 欄位 | 型別 | 說明 |
|------|------|------|
| `student_id` | `string` (必填) | 學生學號 |
| `defense_date` | `string` (必填) | 口試日期，格式 `YYYY-MM-DD` |
| `defense_time` | `string` (必填) | 口試時間，例如 `14:00` |
| `final_location` | `string` (必填) | 經 Tool 1 驗證後的完整地點名稱 |
| `final_committee_str` | `string` (必填) | 經 Tool 2 驗證後的委員名單，以逗號分隔 |

* **Response**:
```json
{
  "status": "success",
  "message": "PPT 佈告已順利生成！",
  "download_url": "http://127.0.0.1:8088/downloads/defense_M11402165_1.pptx"
}
```

---

## 靜態檔案服務 (Static File Serving)
生成的 PPT 檔案存放於 `backend/downloads/` 目錄，透過 FastAPI `StaticFiles` 掛載於 `/downloads` 路徑提供下載。
* **路徑格式**: `GET /downloads/{filename}`
* **範例**: `http://127.0.0.1:8088/downloads/defense_M11402165_1.pptx`