import os
import json
import difflib
from datetime import datetime
from fastapi import FastAPI, Depends, Query, HTTPException, Header
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles 
from sqlalchemy.orm import Session
from dotenv import load_dotenv

import schemas 
import models
from database import engine, get_db
from services.generator import generate_ppt
from contextlib import asynccontextmanager
from seed import run_seed
# 新增一個 Chat 路由來串接 Dify
from pydantic import BaseModel
import requests

class ChatRequest(BaseModel):
    query: str
# ==========================================
# 初始化資料庫 (如果資料表不存在就建立)
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("啟動中：正在檢查與初始化資料庫...")
    models.Base.metadata.create_all(bind=engine)
    run_seed() # <--- 啟動時自動讀取 CSV 並把資料塞進資料庫
    yield
    print("伺服器關閉中...")

# 載入 .env 檔案
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_PATH)

# 讀取環境變數，如果沒讀到，就預設給 127.0.0.1 避免程式當掉
SERVER_URL = os.getenv("SERVER_URL", "http://127.0.0.1:8088")

app = FastAPI(
    title="Defense-Bot API",
    lifespan=lifespan,
    description="智慧口試佈告生成系統的後端 API )",
    servers=[
        {
            "url": SERVER_URL,  
            "description": "API 伺服器"
        }
    ]
)

# 設定 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 設定檔案下載路由 (掛載靜態資料夾)
DOWNLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "downloads"))
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
app.mount("/downloads", StaticFiles(directory=DOWNLOAD_DIR), name="downloads")


# ==========================================
#  模擬身份驗證攔截器 (Auth Dependency)
# ==========================================
def get_current_student_id(x_student_id: str = Header(None, description="模擬登入的學號 (例如: M11402165)")):
    if not x_student_id:
        raise HTTPException(status_code=401, detail="未登入或缺乏身份憑證 (Missing X-Student-ID Header)")
    return x_student_id


# ==========================================
# API 路由 (Routes)
# ==========================================

@app.get("/")
def root():
    return {"status": "running", "message": " Defense-Bot Backend is up and running!"}

# ------------------------------------------
#  新增：前端專用 API (個人首頁與歷史紀錄)
# ------------------------------------------
@app.get("/api/v1/students/me", summary="取得當前登入學生的個人檔案")
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

@app.get("/api/v1/defense/history", summary="取得歷史口試佈告紀錄")
def get_my_history(student_id: str = Depends(get_current_student_id), db: Session = Depends(get_db)):
    logs = db.query(models.DefenseLog).filter(models.DefenseLog.student_id == student_id).order_by(models.DefenseLog.created_at.desc()).all()
    return [
        {
            "log_id": log.log_id,
            "created_at": log.created_at,
            "defense_date": log.defense_date_text,
            "location": log.location_full_text,
            "download_url": log.generated_file_url
        }
        for log in logs
    ]

# ------------------------------------------
#  學生查詢 API
# ------------------------------------------
@app.get("/api/v1/students/lookup")
def lookup_student(q: str = Query(..., description="學號或姓名"), db: Session = Depends(get_db)):
    students = db.query(models.Student).filter(
        (models.Student.student_id.like(f"%{q}%")) | 
        (models.Student.student_name.like(f"%{q}%"))
    ).all()
    
    matches = []
    for s in students:
        advisor_text = ""
        if s.advisor:
            advisor_text = f"{s.advisor.professor_name} {s.advisor.professor_title} {s.advisor.department_name}"
        
        matches.append({
            "student_id": s.student_id,
            "student_name": s.student_name,
            "thesis_title_zh": s.thesis_title_zh,
            "thesis_title_en": s.thesis_title_en,
            "advisor_info": {
                "professor_name": s.advisor.professor_name if s.advisor else "",
                "full_text": advisor_text
            }
        })
    return {"status": "success", "matches": matches}

@app.get("/api/v1/professors/search")
def search_professor(q: str = Query(..., description="教授姓名"), threshold: int = 70, db: Session = Depends(get_db)):
    professors = db.query(models.Professor).filter(
        models.Professor.professor_name.like(f"%{q}%")
    ).all()
    results = []
    for p in professors:
        results.append({
            "professor_id": p.professor_id,
            "professor_name": p.professor_name,
            "full_text": f"{p.professor_name} {p.professor_title} {p.department_name}",
            "similarity_score": 100 
        })
    return {"status": "success", "results": results}

@app.get("/api/v1/locations/search")
def search_location(q: str = Query(..., description="地點關鍵字"), db: Session = Depends(get_db)):
    locations = db.query(models.DefenseLocation).filter(
        (models.DefenseLocation.room_number.like(f"%{q}%")) | 
        (models.DefenseLocation.building_name.like(f"%{q}%")) |
        (models.DefenseLocation.full_location_name.like(f"%{q}%"))
    ).all()
    results = []
    for loc in locations:
        results.append({
            "location_id": loc.location_id,
            "full_location_name": loc.full_location_name
        })
    return {"status": "success", "results": results}


# ==========================================
#  核心優化：防呆中繼站 API (日期轉換、模糊糾錯、數量防呆、寫入資料庫)
# ==========================================
@app.post("/api/v1/defense/save_info")
def save_defense_info(
    payload: schemas.DefenseInfoSave, 
    student_id: str = Depends(get_current_student_id), # 👈 學號改由 Header 取得
    db: Session = Depends(get_db)
):
    # 1. 檢查這個學生存不存在
    student = db.query(models.Student).filter(models.Student.student_id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="查無此學生資料")

    # 2.  自動轉換民國日期
    try:
        dt = datetime.strptime(payload.defense_date, "%Y-%m-%d")
        roc_year = dt.year - 1911
        weekdays = ["一", "二", "三", "四", "五", "六", "日"]
        formatted_date = f"民國{roc_year}年{dt.month}月{dt.day}日(星期{weekdays[dt.weekday()]})"
    except ValueError:
        formatted_date = payload.defense_date 

    # 3.  地點模糊比對補全
    location = db.query(models.DefenseLocation).filter(
        (models.DefenseLocation.room_number.ilike(f"%{payload.location_keyword}%")) |
        (models.DefenseLocation.full_location_name.ilike(f"%{payload.location_keyword}%"))
    ).first()
    final_location = location.full_location_name if location else payload.location_keyword

    # 4.  委員名單模糊比對與糾錯
    all_profs = db.query(models.Professor).all()
    prof_names = [p.professor_name for p in all_profs]
    prof_dict = {p.professor_name: p for p in all_profs}

    final_committee = []
    for raw_name in payload.committee_members:
        clean_name = raw_name.replace("教授", "").replace("博士", "").strip()
        matches = difflib.get_close_matches(clean_name, prof_names, n=1, cutoff=0.6)
        if matches:
            matched_prof = prof_dict[matches[0]]
            full_title = f"{matched_prof.professor_name} {matched_prof.professor_title} {matched_prof.department_name}"
            if full_title not in final_committee:
                final_committee.append(full_title)
        else:
            final_committee.append(f"{raw_name} 教授")

    # 5. 自動補上指導教授！
    if student.advisor:
        advisor_full = f"{student.advisor.professor_name} {student.advisor.professor_title} {student.advisor.department_name}"
        if advisor_full not in final_committee:
            final_committee.append(advisor_full)

    # 6. 【委員數量防呆檢核】
    if len(final_committee) < 3:
        raise HTTPException(
            status_code=400, 
            detail=f"委員數量不足！碩士班口試至少需 3 位委員（含指導教授）。目前僅有 {len(final_committee)} 位，請您補充其他委員姓名。"
        )

    # 7. 寫入資料庫 (作為狀態暫存)
    new_log = models.DefenseLog(
        student_id=student.student_id,
        defense_date_text=formatted_date,
        defense_time_text=payload.defense_time,
        location_full_text=final_location,
        committee_json=json.dumps(final_committee, ensure_ascii=False)
    )
    db.add(new_log)
    db.commit()

    return {
        "status": "success", 
        "message": "資料已確認並安全儲存！系統已完成時間格式化與數量檢核。", 
        "final_committee": final_committee,
        "formatted_date": formatted_date
    }


# ==========================================
#  最終產生 PPT API (只依賴 Header 學號)
# ==========================================
@app.post("/api/v1/defense/generate")
def generate_defense_ppt(
    student_id: str = Depends(get_current_student_id), # 👈 學號改由 Header 取得
    db: Session = Depends(get_db)
):
    # 1. 從資料庫把剛才 save_info 存好的最新紀錄撈出來
    log = db.query(models.DefenseLog).filter(models.DefenseLog.student_id == student_id).order_by(models.DefenseLog.log_id.desc()).first()
    student = db.query(models.Student).filter(models.Student.student_id == student_id).first()
    
    if not log or not student:
        raise HTTPException(status_code=404, detail="找不到口試資料，請先執行 save_info 儲存資訊")

    advisor_full = f"{student.advisor.professor_name} {student.advisor.professor_title} {student.advisor.department_name}" if student.advisor else ""
    
    # 2. 組裝一份 100% 正確的資料，準備丟給你的 PPT 產生器
    full_data = schemas.FullPPTData(
        student_id=student.student_id,
        student_name=student.student_name,
        thesis_title_zh=student.thesis_title_zh,
        thesis_title_en=student.thesis_title_en,
        advisor_full_text=advisor_full,
        defense_date_text=log.defense_date_text,
        defense_time_text=log.defense_time_text,
        location_full_text=log.location_full_text if hasattr(log, 'location_full_text') and log.location_full_text else "預設地點",
        committee_members=json.loads(log.committee_json)
    )

    # 3. 呼叫產出 PPT！
    filename = generate_ppt(full_data, log.log_id)
    
    # 4. 解決無法下載的問題：回傳專屬的下載網址，並更新回資料庫供歷史紀錄使用
    download_url = f"{SERVER_URL}/downloads/{filename}"
    log.generated_file_url = download_url
    db.commit()

    return {
        "status": "success",
        "message": "PPT 生成成功！",
        "download_url": download_url
    }
@app.post("/api/v1/chat")
async def chat_proxy(payload: ChatRequest, student_id: str = Depends(get_current_student_id), db: Session = Depends(get_db)):
    # 這裡實作將訊息轉發給 Dify API 的邏輯
    # 您可以在這裡獲取資料庫中的 student 資訊，動態組成 inputs 傳給 Dify
    student = db.query(models.Student).filter(models.Student.student_id == student_id).first()
    
    # 呼叫 Dify API 的範例 (請根據您的 Dify 設定填寫)
    # ... 實作邏輯 ...
    return {"answer": f"您好 {student.student_name}，我已收到您的訊息：{payload.query}"}