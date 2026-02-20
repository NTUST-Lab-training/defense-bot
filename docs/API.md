```markdown
# 🔌 Defense-Bot API 規格文件

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

### 4. 一鍵生成口試佈告 (Generate PPTX)
* **Endpoint**: `POST /api/v1/defense/generate`
* **Request Body**:
```json
{
  "student_id": "M11402165",
  "defense_date_text": "民國 112 年 1 月 13 日 星期五",
  "defense_time_text": "15:00-16:00",
  "location_full_text": "第二教學大樓 T2-202會議室",
  "committee_members": ["鄭瑞光 教授 臺灣科技大學電子工程系"]
}