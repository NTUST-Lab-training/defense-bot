import os
import json
import difflib
import requests
import re
import mimetypes
from datetime import datetime
from contextlib import asynccontextmanager

# 確保 Office Open XML 格式有正確的 MIME 類型
# 在某些 Linux 環境下 mimetypes 資料庫不完整，不補的話 StaticFiles 會回傳 text/plain
mimetypes.add_type("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx")
mimetypes.add_type("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx")
mimetypes.add_type("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx")

from fastapi import FastAPI, Depends, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from dotenv import load_dotenv
from typing import List, Optional

import schemas 
import models
from database import engine, get_db
from services.generator import generate_ppt
from seed import run_seed

# ==========================================
# 請求格式定義 (Pydantic Models) - openapi.json 的核心
# ==========================================
class ChatRequest(BaseModel):
    query: str
    conversation_id: str = ""   # 用來接前端傳來的記憶 ID

class ToolLocationRequest(BaseModel):
    keyword: str = Field(..., description="使用者輸入的地點關鍵字")

class LocationResponse(BaseModel):
    status: str
    full_location_name: Optional[str] = None
    suggestions: Optional[List[str]] = None
    message: Optional[str] = None
    reference_locations: Optional[List[str]] = None


class ToolCommitteeRequest(BaseModel):
    student_id: str = Field(..., description="學生學號 (必填)")
    members: str = Field(..., description="教授名字，多位請用逗號或空白分隔，例如：吳晉賢、鄭瑞光")

class ToolSubmitRequest(BaseModel):
    student_id: str = Field(..., description="學生學號 (必填)")
    defense_date: str = Field(..., description="口試日期，建議格式 YYYY-MM-DD")
    defense_time: str = Field(..., description="口試時間，例如 14:00")
    final_location: str = Field(..., description="驗證過後的完整地點名稱")
    final_committee_str: str = Field(..., description="驗證過後的委員名單，請用逗號分隔，例如：鄭瑞光 教授, 吳晉賢 副教授")

# ==========================================
# 初始化與伺服器設定
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("啟動中：正在檢查與初始化資料庫...")
    models.Base.metadata.create_all(bind=engine)
    run_seed() 
    yield
    print("伺服器關閉中...")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_PATH)

# 因為您在 Linux VM 上，建議預設 IP 指向 VM 的實體 IP
SERVER_URL = os.getenv("SERVER_URL", "http://127.0.0.1:8088")

app = FastAPI(
    title="Defense-Bot API",
    lifespan=lifespan,
    description="智慧口試佈告生成系統的後端 API",
    servers=[{"url": SERVER_URL, "description": "API 伺服器"}]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_no_cache_to_api(request: Request, call_next):
    """對所有 /api/ 回應加上防快取標頭，
    避免瀏覽器用快取的 200 回應繞過登入驗證。"""
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response

DOWNLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "downloads"))
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
# 用需認證的 API endpoint 提供下載

def get_current_student_id(x_student_id: str = Header(None, description="模擬登入的學號")):
    if not x_student_id:
        raise HTTPException(status_code=401, detail="未登入或缺乏身份憑證")
    return x_student_id

# ==========================================
#  需認證的檔案下載 API（取代原本的 StaticFiles）
# ==========================================
@app.get("/api/v1/downloads/{filename}")
def authenticated_download(
    filename: str,
    student_id: str = Depends(get_current_student_id),
    db: Session = Depends(get_db)
):
    """需要身分驗證的檔案下載端點，只允許學生下載自己的檔案"""
    # 安全檢查：防止路徑遍歷攻擊
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="無效的檔案名稱")

    # 查詢此學生的所有紀錄，只比對檔名部分，相容舊格式（http://...）與新格式（/api/v1/...）
    logs = db.query(models.DefenseLog).filter(
        models.DefenseLog.student_id == student_id
    ).all()

    log = None
    for l in logs:
        stored_url = (l.generated_file_url or '').strip()
        # 取出 URL 最後一段作為檔名比對
        stored_filename = stored_url.rstrip('/').split('/')[-1]
        if stored_filename == filename:
            log = l
            break

    if not log:
        raise HTTPException(status_code=403, detail="無權限存取此檔案")

    file_path = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="檔案不存在")

    return FileResponse(
        file_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )

# ==========================================
# 前端專用 API (首頁與歷史紀錄保持不變)
# ==========================================
@app.get("/")
def root():
    return {"status": "running", "message": "Defense-Bot Backend is up and running!"}

@app.get("/api/v1/students/me")
def get_my_profile(student_id: str = Depends(get_current_student_id), db: Session = Depends(get_db)):
    student = db.query(models.Student).filter(models.Student.student_id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="查無此學生資料")
    advisor_text = f"{student.advisor.professor_name} {student.advisor.professor_title} {student.advisor.department_name}" if student.advisor else "尚未分配"
    return {
        "student_id": student.student_id,
        "student_name": student.student_name,
        "thesis_title_zh": student.thesis_title_zh,
        "thesis_title_en": student.thesis_title_en,
        "advisor": advisor_text
    }

@app.get("/api/v1/defense/history")
def get_my_history(student_id: str = Depends(get_current_student_id), db: Session = Depends(get_db)):
    # 先驗證學生是否存在，避免假學號拿到 200 空陣列繞過前端驗證
    student = db.query(models.Student).filter(models.Student.student_id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="查無此學生資料")
    logs = db.query(models.DefenseLog).filter(models.DefenseLog.student_id == student_id).order_by(models.DefenseLog.created_at.desc()).all()

    def normalize_url(url: str) -> str:
        """將所有格式的下載路徑統一為需認證的 /api/v1/downloads/ 路徑"""
        if not url:
            return url
        import re as _re
        # 絕對路徑 → 提取檔名部分
        if url.startswith('http://') or url.startswith('https://'):
            match = _re.search(r'/downloads/(.+)$', url)
            if match:
                return f"/api/v1/downloads/{match.group(1)}"
        # 舊格式 /downloads/xxx → 新格式 /api/v1/downloads/xxx
        if url.startswith('/downloads/') and not url.startswith('/api/'):
            return f"/api/v1{url}"
        return url

    return [{"log_id": log.log_id, "created_at": log.created_at, "defense_date": log.defense_date_text, "location": log.location_full_text, "download_url": normalize_url(log.generated_file_url)} for log in logs]


# ==========================================
# 🤖 Dify Agent 專用 Tools API (ReAct 工作流)
# ==========================================

@app.post("/api/v1/tool/query_location", response_model=LocationResponse, summary="Tool 1: 查詢與驗證地點")
def tool_query_location(payload: ToolLocationRequest, db: Session = Depends(get_db)):
    """提供給 Agent 查詢地點，具備自動補全與伺服器端模糊糾錯功能"""
    keyword = payload.keyword

    all_locations = db.query(models.DefenseLocation).all()
    all_location_names = [loc.full_location_name for loc in all_locations]
    loc_dict = {loc.full_location_name: loc for loc in all_locations}

    # 第一關：SQL ilike 精確模糊比對（建號/房號/全名）
    locations = db.query(models.DefenseLocation).filter(
        (models.DefenseLocation.room_number.ilike(f"%{keyword}%")) |
        (models.DefenseLocation.full_location_name.ilike(f"%{keyword}%")) |
        (models.DefenseLocation.building_name.ilike(f"%{keyword}%"))
    ).all()

    # 情況 1：精確命中一筆，直接補全
    if len(locations) == 1:
        return {
            "status": "success",
            "full_location_name": locations[0].full_location_name,
            "reference_locations": []
        }

    # 情況 2：找到多筆，請 Agent 向使用者確認
    if len(locations) > 1:
        suggestions = [loc.full_location_name for loc in locations[:3]]
        return {
            "status": "needs_clarification",
            "suggestions": suggestions,
            "message": f"找到多個相關地點：{', '.join(suggestions)}。請向使用者確認是哪一個。",
            "reference_locations": []
        }

    # 第二關：伺服器端 difflib 模糊比對（處理錯字/諧音，與 query_committee 邏輯一致）
    close_matches = difflib.get_close_matches(keyword, all_location_names, n=3, cutoff=0.4)

    # 情況 3：difflib 找到唯一近似結果，直接補全
    if len(close_matches) == 1:
        return {
            "status": "success",
            "full_location_name": close_matches[0],
            "reference_locations": []
        }

    # 情況 4：difflib 找到多個近似結果，請 Agent 向使用者確認
    if len(close_matches) > 1:
        return {
            "status": "needs_clarification",
            "suggestions": close_matches,
            "message": f"找到多個相似地點：{', '.join(close_matches)}。請向使用者確認是哪一個。",
            "reference_locations": []
        }

    # 情況 5：兩關都找不到，才把名冊丟給 LLM 做最後的諧音糾錯
    return {
        "status": "not_found",
        "message": f"伺服器比對查無「{keyword}」，請啟動 LLM 諧音糾錯模式，比對 reference_locations。",
        "reference_locations": all_location_names
    }

@app.post("/api/v1/tool/query_committee", summary="Tool 2: 查詢與糾錯委員名單")
def tool_query_committee(payload: ToolCommitteeRequest, db: Session = Depends(get_db)):
    """提供給 Agent 進行委員糾錯、自動補齊指導教授，並篩出找不到的名單"""
    student = db.query(models.Student).filter(models.Student.student_id == payload.student_id).first()
    if not student:
        return {"status": "error", "message": "查無此學生資料"}

    raw_members = re.split(r'[，、,]+', payload.members)
    members_list = [m.strip() for m in raw_members if m.strip()]

    all_profs = db.query(models.Professor).all()
    prof_names = [p.professor_name for p in all_profs]
    prof_dict = {p.professor_name: p for p in all_profs}

    #  準備一份完整的教授名冊，等一下要當作參考書丟給 LLM
    reference_roster = [f"{p.professor_name} {p.professor_title} ({p.department_name})" for p in all_profs]

    final_committee = []
    unmatched = []

    for raw_name in members_list:
        clean_name = raw_name.replace("教授", "").replace("博士", "").replace("副教授", "").strip()
        
        if len(raw_name) >= 4 and any(k in raw_name for k in ["系", "所", "公司", "院", "中心", "處", "局", "部", " "]):
            if raw_name not in final_committee:
                final_committee.append(raw_name)
            continue
        matches = difflib.get_close_matches(clean_name, prof_names, n=1, cutoff=0.6)
        if matches:
            matched_prof = prof_dict[matches[0]]
            full_title = f"{matched_prof.professor_name} {matched_prof.professor_title} ({matched_prof.department_name})"
            if full_title not in final_committee:
                final_committee.append(full_title)
        else:
            unmatched.append(raw_name)

    if student.advisor:
        advisor_full = f"{student.advisor.professor_name} {student.advisor.professor_title} ({student.advisor.department_name})"
        if advisor_full not in final_committee:
            final_committee.append(advisor_full)

    return {
        "status": "success",
        "final_committee": final_committee,  
        "unmatched_names": unmatched,
        # 把全校名單回傳給 LLM 讓他自己做諧音糾錯
        "reference_roster": reference_roster,        
        "is_valid_count": len(final_committee) >= 3,
        "current_count": len(final_committee)
    }


@app.post("/api/v1/tool/submit_and_generate", summary="Tool 3: 最終儲存並生成 PPT")
def tool_submit_and_generate(payload: ToolSubmitRequest, db: Session = Depends(get_db)):
    """Agent 確認所有資料無誤後，一次性寫入資料庫並產出 PPT"""
    student = db.query(models.Student).filter(models.Student.student_id == payload.student_id).first()
    if not student:
        return {"status": "error", "message": "查無此學生資料"}
        
    raw_committee = re.split(r'[，、,]+', payload.final_committee_str)
    final_committee_list = [m.strip() for m in raw_committee if m.strip()]

    try:
        dt = datetime.strptime(payload.defense_date, "%Y-%m-%d")
        roc_year = dt.year - 1911
        weekdays = ["一", "二", "三", "四", "五", "六", "日"]
        formatted_date = f"民國{roc_year}年{dt.month}月{dt.day}日(星期{weekdays[dt.weekday()]})"
    except ValueError:
        formatted_date = payload.defense_date 

    new_log = models.DefenseLog(
        student_id=student.student_id,
        defense_date_text=formatted_date,
        defense_time_text=payload.defense_time,
        location_full_text=payload.final_location,
        committee_json=json.dumps(final_committee_list, ensure_ascii=False)
    )
    db.add(new_log)
    db.commit()

    advisor_full = f"{student.advisor.professor_name} {student.advisor.professor_title} {student.advisor.department_name}" if student.advisor else ""
    full_data = schemas.FullPPTData(
        student_id=student.student_id,
        student_name=student.student_name,
        thesis_title_zh=student.thesis_title_zh,
        thesis_title_en=student.thesis_title_en,
        advisor_full_text=advisor_full,
        defense_date_text=formatted_date,
        defense_time_text=payload.defense_time,
        location_full_text=payload.final_location,
        committee_members=final_committee_list
    )

    filename = generate_ppt(full_data, new_log.log_id)
    # 使用需認證的 API 路徑，確保只有本人能下載
    download_url = f"/api/v1/downloads/{filename}"
    
    new_log.generated_file_url = download_url
    db.commit()

    return {
        "status": "success",
        "message": "PPT 佈告已順利生成！",
        "download_url": download_url
    }

# ==========================================
# 前端對話代理 Proxy (傳遞對話至 Dify)
# ==========================================
@app.post("/api/v1/chat")
def chat_proxy(payload: ChatRequest, student_id: str = Depends(get_current_student_id), db: Session = Depends(get_db)):
    DIFY_API_KEY = os.getenv("DIFY_API_KEY")
    DIFY_API_URL = os.getenv("DIFY_API_URL", "https://api.dify.ai/v1/chat-messages")

    if not DIFY_API_KEY:
        raise HTTPException(status_code=500, detail="後端未設定 Dify API Key")

    student = db.query(models.Student).filter(models.Student.student_id == student_id).first()
    student_name = student.student_name if student else "同學"
    thesis_title = student.thesis_title_zh if student else "尚未設定題目"

    dify_payload = {
        "inputs": {
            "user_name": student_name,
            "thesis_title": thesis_title,
            "current_date": datetime.now().strftime("%Y-%m-%d"),
            "student_id": student_id 
        },
        "query": payload.query,
        "response_mode": "streaming",
        "user": student_id
    }
    
    if payload.conversation_id:
        dify_payload["conversation_id"] = payload.conversation_id

    headers = {
        "Authorization": f"Bearer {DIFY_API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(DIFY_API_URL, json=dify_payload, headers=headers, stream=True)
        if response.status_code != 200:
            raise HTTPException(status_code=500, detail=f"Dify 拒絕請求: {response.text}")
            
        final_answer = ""
        conv_id = "" 
        
        for line in response.iter_lines():
            if line:
                line_str = line.decode('utf-8')
                if line_str.startswith("data: "):
                    try:
                        data = json.loads(line_str[6:]) 
                        
                        if data.get("event") in ["agent_message", "message"]:
                            final_answer += data.get("answer", "")
                        
                        elif data.get("event") == "error":
                            final_answer += f"\n[管家系統提示：{data.get('message', '遭遇未知錯誤')}]"
                        
                        if "conversation_id" in data and not conv_id:
                            conv_id = data["conversation_id"]
                    except json.JSONDecodeError:
                        continue
        
        if not final_answer.strip():
            final_answer = "抱歉，管家剛才沒有聽清楚，或是系統連線稍有延遲，請您再說一次好嗎？"

        return {
            "answer": final_answer,
            "conversation_id": conv_id 
        }

    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail="無法連線至 AI 伺服器")