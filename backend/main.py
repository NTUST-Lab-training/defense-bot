import os
import json
from fastapi import FastAPI, Depends, Query, HTTPException
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

# 初始化資料庫 (如果資料表不存在就建立)

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
    description="智慧口試佈告生成系統的後端 API",
    version="1.0.0",
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
# API 路由 (Routes)
# ==========================================

@app.get("/")
def root():
    return {"status": "running", "message": " Defense-Bot Backend is up and running!"}

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
# 核心優化：防呆中繼站 API (檢核資料、補全委員、寫入資料庫)
# ==========================================
@app.post("/api/v1/defense/save_info")
def save_defense_info(payload: schemas.DefenseInfoSave, db: Session = Depends(get_db)):
    # 1. 檢查這個學生存不存在，順便撈出他的指導教授
    student = db.query(models.Student).filter(models.Student.student_id == payload.student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="查無此學生資料")

    committee = payload.committee_members

    # 2. 【核心防呆機制】：自動補上指導教授！
    # 如果 LLM 忘記把指導教授加進委員名單，我們在這裡用程式強制補上
    if student.advisor:
        advisor_name = student.advisor.professor_name
        # 檢查委員名單裡有沒有包含指導教授的名字
        if not any(advisor_name in member for member in committee):
            advisor_full_text = f"{student.advisor.professor_name} {student.advisor.professor_title} {student.advisor.department_name}"
            committee.append(advisor_full_text) # 強制加入名單！

    # 3. 寫入資料庫 (作為狀態暫存)
    # 這裡將 LLM 收集到的資訊存入 DefenseLog
    new_log = models.DefenseLog(
        student_id=payload.student_id,
        defense_date_text=payload.defense_date_text,
        defense_time_text=payload.defense_time_text,
        location_full_text=payload.location_full_text,
        committee_json=json.dumps(committee, ensure_ascii=False)
    )
    db.add(new_log)
    db.commit()

    return {"status": "success", "message": "資料已確認並安全儲存", "final_committee": committee}


# ==========================================
# 最終產生 PPT API (只吃學號)
# ==========================================
@app.post("/api/v1/defense/generate")
def generate_defense_ppt(req: schemas.GeneratePPTRequest, db: Session = Depends(get_db)):
    # 1. 從資料庫把剛才 save_info 存好的最新紀錄撈出來
    log = db.query(models.DefenseLog).filter(models.DefenseLog.student_id == req.student_id).order_by(models.DefenseLog.log_id.desc()).first()
    student = db.query(models.Student).filter(models.Student.student_id == req.student_id).first()
    
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
        # 【修正】正確從資料庫 (log) 讀取地點
        location_full_text=log.location_full_text if hasattr(log, 'location_full_text') and log.location_full_text else "預設地點",
        committee_members=json.loads(log.committee_json)
    )

    # 3. 呼叫魔法服務產出 PPT！
    filename = generate_ppt(full_data, log.log_id)
    
    # 4. 【解決無法下載的問題】：直接回傳一段專屬的下載網址給 Dify
    download_url = f"{SERVER_URL}/downloads/{filename}"
    return {
        "status": "success",
        "message": "PPT 生成成功！",
        "download_url": download_url
    }