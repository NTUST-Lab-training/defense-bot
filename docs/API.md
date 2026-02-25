# Defense-Bot API 規格文件

* **Base URL**: `http://localhost:8088`
* **API Prefix**: `/api/v1`

##  全域身分驗證機制 (Authentication)
為了落實「零信任架構 (Zero-Trust)」，所有核心操作與寫入 API 皆不再從 Request Body 接收學號，而是必須在 HTTP Header 帶上學生身分憑證（模擬登入狀態）：
* **Header Name**: `x-student-id`
* **Type**: `string`
* **Example**: `M11402165`

---

##  前端專屬 API (Frontend RESTful)

### 1. 取得個人首頁資訊 (Get My Profile)
* **Endpoint**: `GET /api/v1/students/me`
* **Auth Required**: **Yes** (`x-student-id` in Header)
* **說明**: 取得當前登入學生的基本資料與指導教授，供前端畫面渲染與 Context Injection 使用。
* **Response**:
```json
{
  "student_id": "M11402165",
  "student_name": "趙祈佑",
  "thesis_title_zh": "智慧口試佈告生成系統",
  "thesis_title_en": "Intelligent Defense Poster Generation System",
  "advisor": "呂政修 教授 臺灣科技大學電子工程系"
}
```

### 2. 取得歷史口試紀錄 (Get My History)
* **Endpoint**: `GET /api/v1/defense/history`
* **Auth Required**: **Yes** (`x-student-id` in Header)
* **說明**: 取得該學生過去生成的所有口試佈告草稿與下載連結，供前端實作「歷史紀錄儀表板」。
* **Response**:
```json
[
  {
    "log_id": 1,
    "created_at": "2026-02-26T14:30:00",
    "defense_date": "民國115年3月4日(星期三)",
    "location": "第二教學大樓 T2-202會議室",
    "download_url": "[http://127.0.0.1:8088/downloads/defense_M11402165.pptx](http://127.0.0.1:8088/downloads/defense_M11402165.pptx)"
  }
]
```

---

##  公開查詢 API (Public Search)
*(提供給前端表單即時搜尋或未來擴充使用)*

### 3. 身份智慧查詢 (Lookup Student)
* **Endpoint**: `GET /api/v1/students/lookup`
* **Query Params**: `q` (學號或姓名)

### 4. 教授模糊搜尋 (Fuzzy Search Professor)
* **Endpoint**: `GET /api/v1/professors/search`
* **Query Params**: `q` (教授姓名), `threshold` (預設 70)

### 5. 地點查詢 (Search Location)
* **Endpoint**: `GET /api/v1/locations/search`
* **Query Params**: `q` (地點關鍵字)

---

##  兩階段生成 API 
為了根除 LLM 幻覺、降低 AI 數學運算負擔並防止越權竄改，生成 PPT 流程拆分為以下兩階段：

### 6. 第一階段：資料洗滌與防呆存檔 (Save Defense Info)
* **Endpoint**: `POST /api/v1/defense/save_info`
* **Auth Required**: **Yes** (`x-student-id` in Header)
* **說明**: LLM 收集完原始資料後呼叫。**剝奪 AI 的排版與運算權**，後端將主動執行：
  1. 西元日期自動轉換為民國年與星期。
  2. 地點關鍵字模糊比對補全。
  3. 委員名單錯字糾錯（Fuzzy Search）並補全職稱。
  4. 強制自動補全指導教授。
* **Request Body ( schemas.DefenseInfoSave )**:
```json
{
  "defense_date": "2026-03-04",
  "defense_time": "14:00",
  "location_keyword": "T2-202",
  "committee_members": ["鄭瑞洸"] 
}
```

### 7. 第二階段：極簡安全生成 (Generate PPTX)
* **Endpoint**: `POST /api/v1/defense/generate`
* **Auth Required**: **Yes** (`x-student-id` in Header)
* **說明**: 剝奪 LLM 的資料控制權。後端直接從 Header 取得身分憑證，並自資料庫獲取 **最新且精確的暫存資料進行 PPT 組合**，回傳靜態下載連結。
* **Request Body**: `None` (無需傳送任何 Body 參數，達成極致防呆)
* **Response**:
```json
{
  "status": "success",
  "message": "PPT 生成成功！",
  "download_url": "[http://127.0.0.1:8088/downloads/defense_M11402165.pptx](http://127.0.0.1:8088/downloads/defense_M11402165.pptx)"
}
```