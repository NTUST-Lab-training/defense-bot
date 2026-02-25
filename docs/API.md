# Defense-Bot API 規格文件

* **Base URL**: `http://localhost:8088`
* **API Prefix**: `/api/v1`

## API 端點清單

### 1. 身份智慧查詢 (Lookup Student)
* **Endpoint**: `GET /api/v1/students/lookup`
* **Query Params**: `q` (學號或姓名)

### 2. 教授模糊搜尋 (Fuzzy Search Professor)
* **Endpoint**: `GET /api/v1/professors/search`
* **Query Params**: `q` (教授姓名), `threshold` (預設 70)

### 3. 地點查詢 (Search Location)
* **Endpoint**: `GET /api/v1/locations/search`
* **Query Params**: `q` (地點關鍵字)


### 兩階段防禦性生成 API
為了根除 LLM 幻覺與資訊缺漏，生成 PPT 流程拆分為以下兩階段：

#### 4. 第一階段：資料檢核與防呆存檔 (Save Defense Info)
* **Endpoint**: `POST /api/v1/defense/save_info`
* **說明**: LLM 收集完資料後呼叫。後端將主動檢查名單，**若缺乏指導教授將自動補全**，並存入狀態資料庫。
* **Request Body ( schemas.DefenseInfoSave )**:
```json
{
  "student_id": "M11402165",
  "defense_date_text": "民國115年6月20日(星期六)",
  "defense_time_text": "14:00",
  "location_full_text": "第二教學大樓 T2-202會議室",
  "committee_members": ["鄭瑞光 教授 臺灣科技大學電子工程系"]
}
```
#### 5. 第二階段：極簡安全生成 (Generate PPTX)
* **Endpoint**: `POST /api/v1/defense/generate`
* **說明**: 不讓 LLM 有排版控制權。只接受學號，後端自資料庫獲取 **精確的暫存資料進行 PPT 組合**，並回傳靜態下載連結。
* **Request Body ( schemas.DefenseInfoSave )**:
```json
{
  "student_id": "M11402165"
}
```
```json
{
  "status": "success",
  "message": "PPT 生成成功！",
  "download_url": "[http://127.0.0.1:8088/downloads/defense_M11402165.pptx](http://127.0.0.1:8088/downloads/defense_M11402165.pptx)"
}
```