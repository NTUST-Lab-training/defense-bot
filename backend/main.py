import os
import json
import difflib
import requests
import re
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
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

# ✨ 新增：統一改為 POST 後，地點查詢的 Request 模型
class ToolLocationRequest(BaseModel):
    keyword: str = Field(..., description="使用者輸入的地點關鍵字")

# ✨ 新增：明確定義地點查詢的 Response 模型，避免 Dify 解析失敗
class LocationResponse(BaseModel):
    status: str
    full_location_name: Optional[str] = None
    suggestions: Optional[List[str]] = None
    message: Optional[str] = None

# ✨ 為了配合 openapi.json 與 LLM 的不可控性，所有 Array 欄位都降級為 String 處理
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
SERVER_URL = os.getenv("SERVER_URL", "http://192.168.109.128:8088")

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

DOWNLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "downloads"))
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
app.mount("/downloads", StaticFiles(directory=DOWNLOAD_DIR), name="downloads")

def get_current_student_id(x_student_id: str = Header(None, description="模擬登入的學號")):
    if not x_student_id:
        raise HTTPException(status_code=401, detail="未登入或缺乏身份憑證")
    return x_student_id

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
    logs = db.query(models.DefenseLog).filter(models.DefenseLog.student_id == student_id).order_by(models.DefenseLog.created_at.desc()).all()
    return [{"log_id": log.log_id, "created_at": log.created_at, "defense_date": log.defense_date_text, "location": log.location_full_text, "download_url": log.generated_file_url} for log in logs]


# ==========================================
# 🤖 Dify Agent 專用 Tools API (ReAct 工作流)
# ==========================================

# ✨ 這裡已改為 @app.post，並使用 ToolLocationRequest 來接收 JSON Body
@app.post("/api/v1/tool/query_location", response_model=LocationResponse, summary="Tool 1: 查詢與驗證地點")
def tool_query_location(payload: ToolLocationRequest, db: Session = Depends(get_db)):
    print(f"\n==================================================")
    print(f"➡️ [除錯追蹤] 1. 成功進入 query_location API！")
    print(f"➡️ [除錯追蹤] 2. 收到的 keyword: {payload.keyword}")
    
    try:
        keyword = payload.keyword
        print(f"➡️ [除錯追蹤] 3. 準備開始向 SQLite 資料庫查詢...")
        
        locations = db.query(models.DefenseLocation).filter(
            (models.DefenseLocation.room_number.ilike(f"%{keyword}%")) |
            (models.DefenseLocation.full_location_name.ilike(f"%{keyword}%")) |
            (models.DefenseLocation.building_name.ilike(f"%{keyword}%")) 
        ).all()
        
        print(f"➡️ [除錯追蹤] 4. 資料庫查詢完成！共找到 {len(locations)} 筆資料")
        
        if len(locations) == 1:
            print(f"➡️ [除錯追蹤] 5. 進入單筆命中邏輯，準備回傳 success")
            return {"status": "success", "full_location_name": locations[0].full_location_name}
        
        elif len(locations) > 1:
            suggestions = [loc.full_location_name for loc in locations[:3]]
            print(f"➡️ [除錯追蹤] 5. 進入多筆命中邏輯，準備回傳 needs_clarification")
            return {
                "status": "needs_clarification", 
                "suggestions": suggestions,
                "message": f"找到多個相關地點：{', '.join(suggestions)}。請向使用者確認是哪一個。"
            }
        
        print(f"➡️ [除錯追蹤] 5. 進入找不到邏輯，準備回傳 not_found")
        return {
            "status": "not_found", 
            "message": f"校內資料庫查無「{keyword}」。請向使用者確認是否有錯字，或引導使用者回覆「直接使用這個地點」。"
        }

    except Exception as e:
        print(f"❌ [除錯追蹤] 崩潰了！發生嚴重錯誤: {str(e)}")
        # 故意把錯誤往上拋，讓 FastAPI 吐出 500 錯誤
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        print(f"==================================================\n")


@app.post("/api/v1/tool/query_committee", summary="Tool 2: 查詢與糾錯委員名單")
def tool_query_committee(payload: ToolCommitteeRequest, db: Session = Depends(get_db)):
    """提供給 Agent 進行委員糾錯、自動補齊指導教授，並篩出找不到的名單"""
    student = db.query(models.Student).filter(models.Student.student_id == payload.student_id).first()
    if not student:
        return {"status": "error", "message": "查無此學生資料"}

    raw_members = re.split(r'[，、,\s]+', payload.members)
    members_list = [m.strip() for m in raw_members if m.strip()]

    all_profs = db.query(models.Professor).all()
    prof_names = [p.professor_name for p in all_profs]
    prof_dict = {p.professor_name: p for p in all_profs}

    final_committee = []
    unmatched = []

    for raw_name in members_list:
        clean_name = raw_name.replace("教授", "").replace("博士", "").replace("副教授", "").strip()
        
        if len(raw_name) >= 4 and ("系" in raw_name or "所" in raw_name or "公司" in raw_name):
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
    download_url = f"{SERVER_URL}/downloads/{filename}"
    
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