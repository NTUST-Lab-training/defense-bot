from pydantic import BaseModel, Field
from typing import List

# ==========================================
# 1. 中繼站表單：給 LLM 收集完資料後「存檔檢核」用 (2.0 降載版)
# ==========================================
class DefenseInfoSave(BaseModel):
    defense_date: str = Field(..., description="西元口試日期 (例如：2026-06-20，交由後端轉民國年)")
    defense_time: str = Field(..., description="口試時間 (例如：14:00)")
    location_keyword: str = Field(..., description="LLM 聽到的地點簡稱 (例如：T2-202，交由後端補全)")
    committee_members: List[str] = Field(..., description="LLM 聽到的委員名單陣列 (包含錯字也沒關係，交由後端糾錯)")

# ==========================================
# 2. 內部核心表單：後端自己組裝好，餵給 PPT 產生器用的 (不給外部看，維持原樣)
# ==========================================
class FullPPTData(BaseModel):
    student_id: str
    student_name: str
    thesis_title_zh: str = ""
    thesis_title_en: str = ""
    advisor_full_text: str
    defense_date_text: str
    defense_time_text: str
    location_full_text: str
    committee_members: List[str]