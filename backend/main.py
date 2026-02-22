from fastapi import FastAPI, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List
import json

import models
from database import engine, get_db

# 1. 自動建立 SQLite 資料表 (若已存在則不會覆蓋)
models.Base.metadata.create_all(bind=engine)

# 2. 初始化 FastAPI 應用程式
app = FastAPI(
    title="Defense-Bot API",
    description="智慧口試佈告生成系統的後端 API",
    version="1.0.0"
)

# 3. 設定 CORS (允許未來 React 前端跨網域連線)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# Pydantic Schemas (定義請求與回應的資料格式驗證)
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
# API 路由 (Routes)
# ==========================================

@app.get("/")
def root():
    return {"status": "running", "message": "🚀 Defense-Bot Backend is up and running!"}

@app.get("/api/v1/students/lookup")
def lookup_student(q: str = Query(..., description="學號或姓名"), db: Session = Depends(get_db)):
    """身分智慧查詢：用學號或姓名找學生與論文題目"""
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
    """教授模糊搜尋：輸入名字，補全完整職稱與系所"""
    # 目前先用簡單的 SQL LIKE 實作 (未來可擴充為 fuzz 模糊演算法)
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
    """地點查詢：輸入關鍵字，回傳標準化地點名稱"""
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
    """一鍵生成口試佈告 (將前端收集好的資料寫入 Log，並觸發 PPT 產出)"""
    
    # 將生成紀錄存入資料庫
    new_log = models.DefenseLog(
        student_id=payload.student_id,
        defense_date_text=payload.defense_date_text,
        defense_time_text=payload.defense_time_text,
        committee_json=json.dumps(payload.committee_members, ensure_ascii=False)
    )
    db.add(new_log)
    db.commit()
    db.refresh(new_log)
    
    # TODO: 下一階段會在這裡呼叫 services/generator.py 實際寫入 PPTX
    return {
        "status": "success",
        "message": "資料已確認並紀錄。PPT 生成模組開發中！",
        "data": {
            "log_id": new_log.log_id,
            "download_url": "http://localhost:8088/downloads/defense_mock.pptx"
        }
    }