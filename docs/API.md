# Defense-Bot API 規格文件

* **Base URL**: `http://localhost:8088`
* **API Prefix**: `/api/v1`
* **互動式文件**: `http://<BACKEND_HOST_OR_IP>:8088/docs`（或 `https://<BACKEND_PUBLIC_DOMAIN_OR_IP>/docs`，Swagger UI）

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
* **說明**: 取得該學生過去生成的所有口試佈告草稿與下載連結，供前端實作「歷史紀錄儀表板」。回傳結果依建立時間降冪排序。`download_url` 回傳需身份驗證的下載端點路徑（如 `/api/v1/downloads/filename.pptx`）。
* **Response**:
```json
[
  {
    "log_id": 1,
    "created_at": "2026-02-26T14:30:00",
    "defense_date": "民國115年3月4日(星期三)",
    "location": "第二教學大樓 T2-202會議室",
    "download_url": "/api/v1/downloads/defense_M11402165_1.pptx"
  }
]
```

### 4. 對話代理 (Chat Proxy to Dify Agent)
* **Endpoint**: `POST /api/v1/chat`
* **Auth Required**: **Yes** (`x-student-id` in Header)
* **說明**: 前端對話的核心入口。後端會自動注入當前學生的姓名、論文題目、學號與當前日期作為 Dify Agent 的 `inputs`，並以 Streaming 模式接收 Dify 回應後組裝為完整文字回傳。同時維護 `conversation_id` 以延續多輪對話記憶。
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

* **Dify inputs 注入內容**（後端自動組裝，不需前端傳入）：

| 欄位 | 說明 |
|------|------|
| `user_name` | 學生姓名 |
| `thesis_title` | 中文論文題目 |
| `student_id` | 學生學號（供 Agent 呼叫 Tool API 時使用） |
| `current_date` | 當前日期（格式 YYYY-MM-DD） |

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
* **說明**: 接收使用者輸入的地點關鍵字，依序執行**兩階段**模糊比對邏輯：
  1. **第一關：SQL ilike 模糊比對**：對 `room_number`、`full_location_name`、`building_name` 三欄位同時比對。
     - **命中唯一筆** → 直接回傳 `success`，補全地點名稱。
     - **命中多筆** → 回傳 `needs_clarification` 與至多 3 筆建議。
  2. **第二關：`difflib` 模糊比對**（cutoff=0.4）：第一關查無結果時啟動，處理錯字與諧音。
     - **近似唯一筆** → 直接補全回傳 `success`。
     - **近似多筆** → 回傳 `needs_clarification`，請 Agent 向使用者確認。
  3. **兩關都查無結果** → 回傳 `not_found` 與全校地點名冊 (`reference_locations`)，讓 LLM 發揮諧音糾錯能力自行比對。
* **Request Body**:
```json
{
  "keyword": "T2-202"
}
```
* **Response（第一/二關命中唯一筆 → `success`）**:
```json
{
  "status": "success",
  "full_location_name": "第二教學大樓 T2-202會議室",
  "suggestions": null,
  "message": null,
  "reference_locations": []
}
```
* **Response（命中多筆 → `needs_clarification`）**:
```json
{
  "status": "needs_clarification",
  "full_location_name": null,
  "suggestions": ["第二教學大樓 T2-202會議室", "第二教學大樓 T2-210教室"],
  "message": "找到多個相關地點：....。請向使用者確認是哪一個。",
  "reference_locations": []
}
```
* **Response（兩關都查無結果 → 啟動 LLM 諧音糾錯模式）**:
```json
{
  "status": "not_found",
  "full_location_name": null,
  "suggestions": null,
  "message": "伺服器比對查無「T2-999」，請啟動 LLM 諧音糾錯模式，比對 reference_locations。",
  "reference_locations": ["電資館 EE-703-1 實驗室", "國際大樓 IB-201 會議室", "..."]
}
```

### 6. Tool 2：查詢與糾錯委員名單 (Query Committee)
* **Endpoint**: `POST /api/v1/tool/query_committee`
* **Auth Required**: **No** (Dify Agent 直接呼叫)
* **說明**: 接收學生學號與粗略的委員名字清單，執行以下防禦性邏輯：
  1. 先做職稱解析（如「教授 / 副教授 / 博士」），避免把職稱誤當姓名。
  2. 以混合相似度（`difflib` + 字元重疊 + n-gram）做模糊比對，自動糾錯並補全職稱與系所。
  3. 若輸入已含職稱與單位線索（如「某某教授 某某系」），直接視為外部/業界成員加入 `external_members`。
  4. 對於已有職稱但缺單位的名字（如「張忠謀教授」），若 `difflib` 分數偏低，直接回傳 `needs_manual_profile` 與 `manual_profile_requirements: {"張忠謀教授": ["organization"]}`，避免 LLM 重複詢問候選。
  5. 對於其他 `difflib` 分數偏低且無法直接命中的名字，回傳 `llm_compare_required`、`candidate_matches` 與 `reference_roster_lite`（精簡候選）供 LLM 自行糾錯判斷（不問使用者），避免每次都掃全量名冊。
  6. 對於完全無線索的名字，回傳 `needs_manual_profile` 與 `manual_profile_requirements`（缺少 `title` 或 `organization`），引導 Agent 精準追問缺項。
  6. **強制自動補入指導教授**（即使使用者未提及）。
  7. 回傳 `next_action`、`required_profile_fields`、`agent_hint`，引導對話進入「候選確認 / 補填資料」流程。
  8. 回傳 `is_valid_count` 旗標，標示委員人數是否已達到 3 人門檻。
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
  "external_members": [],
  "needs_manual_profile": [],
  "manual_profile_requirements": {},
  "candidate_matches": {},
  "reference_roster_lite": [],
  "llm_compare_required": [],
  "next_action": "continue_checklist",
  "required_profile_fields": ["name", "title", "organization"],
  "agent_hint": "若 llm_compare_required 非空，請先依 candidate_matches 與上下文自行判斷最可能的教授並直接採用；僅在無合理候選時才改走補資料流程。若 needs_manual_profile 非空，請只詢問 manual_profile_requirements 指定的缺少欄位，避免重複詢問是否為校內名冊教授。",
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
  "download_url": "/api/v1/downloads/defense_M11402165_1.pptx"
}
```

> **注意**：`download_url` 回傳需身份驗證的 API 路徑，學生透過前端傳遞 `x-student-id` Header 後可下載。

---

## 前端專屬 API（續）

### 5. 認證下載 PPT 檔案 (Authenticated Download)
* **Endpoint**: `GET /api/v1/downloads/{filename}`
* **Auth Required**: **Yes** (`x-student-id` in Header)
* **說明**: 需身份驗證的 PPT 下載端點。系統會驗證該學號是否為 PPT 的所有者，只允許學生下載自己生成的檔案。前端應透過此端點搭配 `x-student-id` Header 進行下載。
* **Parameters**:

| 名稱 | 位置 | 型別 | 說明 |
|------|------|------|------|
| `filename` | URL Path | `string` | 要下載的 PPT 檔案名稱（例如 `defense_M11402165_1.pptx`） |
| `x-student-id` | Header | `string` | 學生學號，用於驗證下載權限 |

* **Response**:
  - **成功 (200)**: 回傳 PPT 檔案（MIME 類型：`application/vnd.openxmlformats-officedocument.presentationml.presentation`）
  - **無權限 (403)**: `{"detail": "無權限存取此檔案"}`
  - **檔案不存在 (404)**: `{"detail": "檔案不存在"}`
  - **未登入 (401)**: `{"detail": "未登入或缺乏身份憑證"}`

---

## 靜態檔案服務 (Static File Serving)
生成的 PPT 檔案存放於 `backend/downloads/` 目錄，透過身份驗證的 `/api/v1/downloads/{filename}` 端點提供下載。前端應使用此端點搭配 `x-student-id` Header 進行檔案下載，確保用戶只能下載自己的檔案。
* **存放位置**: `backend/downloads/{filename}`
* **下載格式**: `GET /api/v1/downloads/{filename}` (需 `x-student-id` Header)
* **檔案名稱規則**: `defense_{學號}_{log_id}.pptx` (例如 `defense_M11402165_1.pptx`)

> Linux 環境下已在程式層主動註冊 `.pptx` 的 MIME 類型 (`application/vnd.openxmlformats-officedocument.presentationml.presentation`)，避免某些 Linux 底層 mimetypes 資料庫不完整導致回傳 `text/plain`。