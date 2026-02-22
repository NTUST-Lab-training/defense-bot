import os
from fastapi import FastAPI, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles # 新增：用來提供檔案下載
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List
import json

import models
from database import engine, get_db
from services.generator import generate_ppt # 新增：匯入我們的生成器

models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Defense-Bot API",
    description="智慧口試佈告生成系統的後端 API",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 新增：設定檔案下載路由
# 這樣只要訪問 http://127.0.0.1:8088/downloads/檔名.pptx 就能直接下載！
DOWNLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "downloads"))
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
app.mount("/downloads", StaticFiles(directory=DOWNLOAD_DIR), name="downloads")

# ==========================================
# Pydantic Schemas
# ==========================================
class GeneratePPTRequest(BaseModel):
    student_id: str
    student_name: str
    thesis_title_zh: str = ""
    thesis_title_en: str = ""
    advisor_full_text: str
    defense_date_text: str
    defense_time_text: str
    location_full_text: str
    committee_members: List[str]

# ==========================================
# API 路由
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

@app.post("/api/v1/defense/generate")
def generate_defense_ppt(payload: GeneratePPTRequest, db: Session = Depends(get_db)):
    # 1. 將生成紀錄存入資料庫
    new_log = models.DefenseLog(
        student_id=payload.student_id,
        defense_date_text=payload.defense_date_text,
        defense_time_text=payload.defense_time_text,
        committee_json=json.dumps(payload.committee_members, ensure_ascii=False)
    )
    db.add(new_log)
    db.commit()
    db.refresh(new_log)
    
    # 2. 呼叫我們剛寫好的魔法服務產出 PPT！
    filename = generate_ppt(payload, new_log.log_id)
    
    # 3. 組合下載網址
    download_url = f"http://127.0.0.1:8088/downloads/{filename}"
    
    return {
        "status": "success",
        "message": "PPT 生成成功！",
        "data": {
            "log_id": new_log.log_id,
            "download_url": download_url
        }
    }