from pydantic import BaseModel, Field
from typing import List

# ==========================================
# 1. 中繼站表單：給 LLM 收集完資料後「存檔檢核」用
# ==========================================
class DefenseInfoSave(BaseModel):
    student_id: str = Field(..., description="學生學號")
    defense_date_text: str = Field(..., description="口試日期 (例如：民國115年6月20日(星期六))")
    defense_time_text: str = Field(..., description="口試時間 (例如：14:00)")
    location_full_text: str = Field(..., description="完整地點名稱")
    committee_members: List[str] = Field(..., description="LLM 查到的委員名單陣列")

# ==========================================
# 2. 最終觸發表單：給 LLM 「產生簡報」用 (極度嚴格，防幻覺)
# ==========================================
class GeneratePPTRequest(BaseModel):
    # 徹底剝奪 LLM 亂塞資料的權力，只准它傳學號進來！
    student_id: str = Field(..., description="學生學號")

# ==========================================
# 3. 內部核心表單：後端自己組裝好，餵給 PPT 產生器用的 (不給外部看)
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