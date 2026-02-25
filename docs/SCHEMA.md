# 實體關聯模型與資料庫設計 (Database Schema)

## 1. 架構說明與技術選型權衡
* **資料庫選型**: 使用 SQLite (`defense.db`)。
* **冪等性與字串主鍵**: 為配合外部 CSV (如 `P001`, `M11402165`) 的「資料驅動播種」機制，所有實體的 ID (PK/FK) 均調整為 `String` 型態。
* **陣列處理**: 因 SQLite 缺乏 `JSONB`，委員名單 (`committee_json`) 宣告為 `String`，由後端 Pydantic Schemas 負責序列化防呆驗證。

## 2. 實體關聯圖 (ER Diagram)

```mermaid
erDiagram
    STUDENT {
        string student_id PK "學號 (e.g., M11402165)"
        string student_name "學生姓名"
        string thesis_title_zh "中文論文題目"
        string thesis_title_en "英文論文題目"
        string advisor_id FK "指導教授 ID (對齊 CSV)"
    }

    PROFESSOR {
        string professor_id PK "教授唯一碼 (e.g., P001)"
        string professor_name "教授姓名"
        string professor_title "職稱"
        string department_name "服務單位"
    }

    DEFENSE_LOCATION {
        string location_id PK "地點唯一碼 (e.g., L001)"
        string building_name "館舍名稱"
        string room_number "教室編號"
        string full_location_name "完整地點組合"
    }

    DEFENSE_LOG {
        int log_id PK "流水號 (Auto Increment)"
        string student_id FK "關聯學生"
        string location_id FK "關聯地點"
        datetime created_at "生成時間"
        string defense_date_text "口試日期字串"
        string defense_time_text "口試時間字串"
        string location_full_text "暫存地點字串"
        string committee_json "口試委員名單 (JSON String)"
        string generated_file_url "下載路徑"
    }

    PROFESSOR ||--o{ STUDENT : "Advises"
    STUDENT ||--o{ DEFENSE_LOG : "Generates"
    DEFENSE_LOCATION ||--o{ DEFENSE_LOG : "Hosts"
```