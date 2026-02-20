```markdown
# 實體關聯模型與資料庫設計 (Database Schema)

## 1. 架構說明與技術選型權衡
* **資料庫選型**: 使用 SQLite (`defense.db`)。
* **選型考量**: 在此輕量級情境下，SQLite 具備極佳的部署便利性。因缺少 PostgreSQL 原生的 `JSONB` 支援，陣列型態資料（如 `committee_json`）統一宣告為 `TEXT`，交由 Python 後端進行解析與驗證。

## 2. 實體關聯圖 (ER Diagram)
```mermaid
erDiagram
    STUDENT {
        string student_id PK "學號"
        string student_name "學生姓名"
        string thesis_title_zh "中文論文題目"
        string thesis_title_en "英文論文題目"
        int advisor_professor_id FK "指導教授 ID"
    }
    PROFESSOR {
        int professor_id PK "教授唯一碼"
        string professor_name "教授姓名"
        string professor_title "職稱"
        string department_name "服務單位"
    }
    DEFENSE_LOCATION {
        int location_id PK "地點唯一碼"
        string building_name "館舍名稱"
        string room_number "教室編號"
        string full_location_name "完整地點組合"
    }
    DEFENSE_LOG {
        int log_id PK "流水號"
        string student_id FK "關聯學生"
        int location_id FK "關聯地點"
        datetime created_at "生成時間"
        string defense_date_text "口試日期字串"
        string defense_time_text "口試時間字串"
        string committee_json "口試委員名單"
        string generated_file_url "下載路徑"
    }

    PROFESSOR ||--o{ STUDENT : "Advises"
    STUDENT ||--o{ DEFENSE_LOG : "Generates"
    DEFENSE_LOCATION ||--o{ DEFENSE_LOG : "Hosts"

---