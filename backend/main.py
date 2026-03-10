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

    # 正規化函式：移除連字號/全形連字號/空白，轉小寫
    # 目的：讓「IB101」能精確比對到資料庫中的「IB-101」
    def normalize(s: str) -> str:
        return re.sub(r'[\s\-\u2010-\u2015\u2212\uFF0D]+', '', s).lower()

    keyword_norm = normalize(keyword)

    # 第零關：以正規化房號做精確比對（最優先，處理省略連字號的輸入）
    # 例：「IB101」→ normalize → 「ib101」，比對 room_number「IB-101」→「ib101」→ 完全吻合
    room_exact = [loc for loc in all_locations if normalize(loc.room_number) == keyword_norm]
    if len(room_exact) == 1:
        return {"status": "success", "full_location_name": room_exact[0].full_location_name, "reference_locations": []}

    # 若正規化精確比對命中多筆（同棟不同室），以 SequenceMatcher 分數取最佳
    if len(room_exact) > 1:
        scored_exact = sorted(
            room_exact,
            key=lambda loc: difflib.SequenceMatcher(None, keyword_norm, normalize(loc.room_number)).ratio(),
            reverse=True
        )
        best, second = scored_exact[0], scored_exact[1]
        if difflib.SequenceMatcher(None, keyword_norm, normalize(best.full_location_name)).ratio() > \
           difflib.SequenceMatcher(None, keyword_norm, normalize(second.full_location_name)).ratio():
            return {"status": "success", "full_location_name": best.full_location_name, "reference_locations": []}

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

    # 情況 2：找到多筆，以正規化房號相似度排序（房號優先，全名次之）
    if len(locations) > 1:
        def similarity(loc):
            room_score = difflib.SequenceMatcher(None, keyword_norm, normalize(loc.room_number)).ratio()
            name_score = difflib.SequenceMatcher(None, keyword_norm, normalize(loc.full_location_name)).ratio()
            return room_score * 0.7 + name_score * 0.3

        scored = sorted(
            [(loc.full_location_name, similarity(loc)) for loc in locations],
            key=lambda x: x[1],
            reverse=True
        )
        best_name, best_score = scored[0]
        second_score = scored[1][1] if len(scored) > 1 else 0.0

        # 最佳結果明顯勝出，視為唯一命中
        if best_score >= 0.4 and (best_score - second_score) >= 0.1:
            return {
                "status": "success",
                "full_location_name": best_name,
                "reference_locations": []
            }

        suggestions = [name for name, _ in scored[:3]]
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

    # 情況 4：difflib 找到多個近似結果，先以分數排序，若最佳明顯勝出就直接補全
    if len(close_matches) > 1:
        def diff_score(name):
            return difflib.SequenceMatcher(None, keyword.lower(), name.lower()).ratio()

        scored_diff = sorted(
            [(name, diff_score(name)) for name in close_matches],
            key=lambda x: x[1],
            reverse=True
        )
        best_name_d, best_score_d = scored_diff[0]
        second_score_d = scored_diff[1][1] if len(scored_diff) > 1 else 0.0

        if best_score_d >= 0.5 and (best_score_d - second_score_d) >= 0.2:
            return {
                "status": "success",
                "full_location_name": best_name_d,
                "reference_locations": []
            }

        return {
            "status": "needs_clarification",
            "suggestions": [name for name, _ in scored_diff[:3]],
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

    def split_members(raw_members_text: str):
        text = (raw_members_text or "").strip()
        if not text:
            return []

        # 先統一常見分隔符
        text = re.sub(r"[，、,;；/｜|\n\t]+", ",", text)
        chunks = [chunk.strip() for chunk in text.split(",") if chunk.strip()]

        title_or_org_hints = [
            "講座教授", "特聘教授", "助理教授", "副教授", "教授", "博士",
            "系", "所", "公司", "院", "中心", "處", "局", "部", "大學", "學院", "研究室", "實驗室", "科大"
        ]

        members = []
        for chunk in chunks:
            # 僅在「看起來是多個純中文姓名」時，才用空白再切一次
            if (
                " " in chunk
                and not re.search(r"[A-Za-z]", chunk)
                and not re.search(r"[()（）\[\]{}【】]", chunk)
                and not any(hint in chunk for hint in title_or_org_hints)
            ):
                spaced_parts = [part.strip() for part in re.split(r"\s+", chunk) if part.strip()]
                if spaced_parts and all(re.fullmatch(r"[\u4e00-\u9fff]{2,4}", p) for p in spaced_parts):
                    members.extend(spaced_parts)
                    continue

            members.append(chunk)

        return members

    members_list = split_members(payload.members)

    all_profs = db.query(models.Professor).all()
    prof_names = [p.professor_name for p in all_profs]
    prof_dict = {p.professor_name: p for p in all_profs}

    title_keywords = ["講座教授", "特聘教授", "助理教授", "副教授", "教授", "博士"]
    org_keywords = ["系", "所", "公司", "院", "中心", "處", "局", "部", "大學", "學院", "研究室", "實驗室", "科大"]

    def normalize_member_text(s: str) -> str:
        return re.sub(r"\s+", "", s or "")

    def normalize_org_text(s: str) -> str:
        org = (s or "").strip()
        org = re.sub(r"^[\s:：,，、\-—]+|[\s:：,，、\-—]+$", "", org)

        # 去除最外層括號，避免輸出時組成 ((單位))
        while org and re.match(r"^[\(\[（【].*[\)\]）】]$", org):
            stripped = re.sub(r"^[\(\[（【]\s*", "", org)
            stripped = re.sub(r"\s*[\)\]）】]$", "", stripped)
            stripped = stripped.strip()
            if stripped == org:
                break
            org = stripped

        return org

    def parse_member(raw_text: str):
        text = raw_text.strip()
        detected_title = ""
        for title in title_keywords:
            if title in text:
                detected_title = title
                break

        has_org_hint = any(k in text for k in org_keywords)

        name_candidate = text
        org_candidate = text

        # 先嘗試「姓名 + 職稱」模式，避免把姓名與單位黏在一起
        if detected_title:
            m = re.search(rf"([\u4e00-\u9fff]{{2,4}})\s*{detected_title}", text)
            if m:
                name_candidate = m.group(1)
                org_candidate = text.replace(m.group(0), "", 1)

        if name_candidate == text:
            for title in title_keywords:
                name_candidate = name_candidate.replace(title, "")
            name_candidate = re.sub(r"[()（）\[\]{}【】]", "", name_candidate)
            name_candidate = re.sub(r"\s+", "", name_candidate)
            name_candidate = re.sub(r"[^\u4e00-\u9fffA-Za-z]", "", name_candidate)

            org_candidate = text
            if name_candidate:
                org_candidate = org_candidate.replace(name_candidate, "")
            if detected_title:
                org_candidate = org_candidate.replace(detected_title, "")

        org_candidate = normalize_org_text(org_candidate)

        return {
            "raw": text,
            "clean_name": name_candidate,
            "detected_title": detected_title,
            "has_org_hint": has_org_hint,
            "org_candidate": org_candidate
        }

    def chinese_name_similarity(input_name: str, prof_name: str) -> float:
        a = normalize_member_text(input_name)
        b = normalize_member_text(prof_name)
        if not a or not b:
            return 0.0

        seq_score = difflib.SequenceMatcher(None, a, b).ratio()

        set_a = set(a)
        set_b = set(b)
        overlap_score = len(set_a & set_b) / max(1, len(set_a | set_b))

        # 通用 n-gram 重疊，避免硬編碼特定姓名或字形規則
        def ngrams(s: str, n: int = 2):
            if len(s) < n:
                return {s} if s else set()
            return {s[i:i+n] for i in range(len(s) - n + 1)}

        ngram_a = ngrams(a, 2)
        ngram_b = ngrams(b, 2)
        ngram_score = len(ngram_a & ngram_b) / max(1, len(ngram_a | ngram_b))

        max_len = max(len(a), len(b))
        position_acc = 0.0
        for idx in range(min(len(a), len(b))):
            if a[idx] == b[idx]:
                position_acc += 1.0
        position_score = position_acc / max(1, max_len)

        return seq_score * 0.35 + overlap_score * 0.2 + ngram_score * 0.2 + position_score * 0.25

    def get_prof_candidates(clean_name: str):
        scored = sorted(
            [(name, chinese_name_similarity(clean_name, name)) for name in prof_names],
            key=lambda x: x[1],
            reverse=True
        )
        return scored[:3]

    def get_best_difflib_score(clean_name: str):
        if not clean_name:
            return "", 0.0
        scored = sorted(
            [(name, difflib.SequenceMatcher(None, normalize_member_text(clean_name), normalize_member_text(name)).ratio()) for name in prof_names],
            key=lambda x: x[1],
            reverse=True
        )
        return scored[0] if scored else ("", 0.0)

    #  準備一份完整的教授名冊，等一下要當作參考書丟給 LLM
    reference_roster = [f"{p.professor_name} {p.professor_title} ({p.department_name})" for p in all_profs]

    final_committee = []
    unmatched = []
    external_members = []
    needs_manual_profile = []
    manual_profile_requirements = {}
    candidate_matches = {}
    candidate_roster_lite = []
    llm_compare_required = []

    # 預先計算指導教授的完整字串，讓迴圈中可以識別並跳過，統一交由底部補齊邏輯排在最末位
    advisor_full = (
        f"{student.advisor.professor_name} {student.advisor.professor_title} ({student.advisor.department_name})"
        if student.advisor else None
    )

    for raw_name in members_list:
        parsed = parse_member(raw_name)
        clean_name = parsed["clean_name"]
        detected_title = parsed["detected_title"]
        has_org_hint = parsed["has_org_hint"]
        org_candidate = parsed["org_candidate"]

        if not clean_name:
            unmatched.append(raw_name)
            if raw_name not in needs_manual_profile:
                needs_manual_profile.append(raw_name)
                manual_profile_requirements[raw_name] = ["name", "title", "organization"]
            continue

        # 顯性外部格式：已提供職稱且帶有單位線索，直接視為校外/業界委員
        if detected_title and has_org_hint:
            external_org = org_candidate if org_candidate else "未提供單位"
            external_full = f"{clean_name} {detected_title} ({external_org})"
            if external_full not in final_committee:
                final_committee.append(external_full)
                external_members.append(external_full)
            continue

        # 完全同名，直接命中
        if clean_name in prof_dict:
            matched_prof = prof_dict[clean_name]
            full_title = f"{matched_prof.professor_name} {matched_prof.professor_title} ({matched_prof.department_name})"
            # 若比對到的是指導教授，跳過不加入，讓底部補齊邏輯統一排在最末位
            if full_title == advisor_full:
                continue
            if full_title not in final_committee:
                final_committee.append(full_title)
            continue

        candidates = get_prof_candidates(clean_name)
        best_name, best_score = candidates[0]
        second_score = candidates[1][1] if len(candidates) > 1 else 0.0
        best_difflib_name, best_difflib_score = get_best_difflib_score(clean_name)

        # 若已有職稱但缺單位，且 difflib 分數低，直接改走補資料流程，避免 LLM 再問使用者確認候選
        if best_difflib_score < 0.5:
            if detected_title and not has_org_hint:
                unmatched.append(raw_name)
                if raw_name not in needs_manual_profile:
                    needs_manual_profile.append(raw_name)
                    manual_profile_requirements[raw_name] = ["organization"]
                continue

            # 其他情況：準備精簡候選供 LLM 自行判斷（不問使用者）
            unmatched.append(raw_name)

            llm_candidates = [name for name, score in candidates if score >= 0.35]
            if not llm_candidates:
                llm_candidates = [name for name, _ in candidates]

            candidate_matches[raw_name] = [
                f"{name} {prof_dict[name].professor_title} ({prof_dict[name].department_name})"
                for name in llm_candidates
            ]
            for item in candidate_matches[raw_name]:
                if item not in candidate_roster_lite:
                    candidate_roster_lite.append(item)

            if raw_name not in llm_compare_required:
                llm_compare_required.append(raw_name)
            continue

        # 分數高且明顯領先，才直接採用
        if best_score >= 0.6 and (best_score - second_score) >= 0.08:
            matched_prof = prof_dict[best_name]
            full_title = f"{matched_prof.professor_name} {matched_prof.professor_title} ({matched_prof.department_name})"
            # 若比對到的是指導教授，跳過不加入，讓底部補齊邏輯統一排在最末位
            if full_title == advisor_full:
                continue
            if full_title not in final_committee:
                final_committee.append(full_title)
            continue

        unmatched.append(raw_name)

        confident_candidates = [name for name, score in candidates if score >= 0.42]
        candidate_matches[raw_name] = [
            f"{name} {prof_dict[name].professor_title} ({prof_dict[name].department_name})"
            for name in confident_candidates
        ]
        for item in candidate_matches[raw_name]:
            if item not in candidate_roster_lite:
                candidate_roster_lite.append(item)

        is_likely_person_name = re.fullmatch(r"[\u4e00-\u9fff]{2,4}", clean_name) is not None
        if is_likely_person_name and not confident_candidates and raw_name not in needs_manual_profile:
            needs_manual_profile.append(raw_name)
            missing_fields = []
            if not detected_title:
                missing_fields.append("title")
            if not has_org_hint:
                missing_fields.append("organization")
            manual_profile_requirements[raw_name] = missing_fields if missing_fields else ["title", "organization"]

    if advisor_full:
        # 指導教授在迴圈中已被識別並跳過，此處直接附加到最末位（防重複）
        if advisor_full not in final_committee:
            final_committee.append(advisor_full)

    if needs_manual_profile:
        next_action = "collect_member_profile"
    elif llm_compare_required:
        next_action = "llm_compare_candidates"
    elif unmatched:
        next_action = "confirm_candidate_matches"
    else:
        next_action = "continue_checklist"

    # 固定同時回傳兩種名冊：精簡候選（reference_roster_lite）+ 完整全名冊（reference_roster）
    return_reference_roster = reference_roster

    return {
        "status": "success",
        "final_committee": final_committee,  
        "unmatched_names": unmatched,
        "external_members": external_members,
        "needs_manual_profile": needs_manual_profile,
        "manual_profile_requirements": manual_profile_requirements,
        "candidate_matches": candidate_matches,
        "reference_roster_lite": candidate_roster_lite,
        "llm_compare_required": llm_compare_required,
        "next_action": next_action,
        "required_profile_fields": ["name", "title", "organization"],
        "agent_hint": "若 llm_compare_required 非空，請先依 candidate_matches 與上下文自行判斷最可能的教授並直接採用；僅在無合理候選時才改走補資料流程。若 needs_manual_profile 非空，請只詢問 manual_profile_requirements 指定的缺少欄位，避免重複詢問是否為校內名冊教授。【重要】向使用者呈現委員名單時，請務必依照 final_committee 的順序排列，指導教授（advisor_info）永遠排在最後一位。",
        "reference_roster": return_reference_roster,
        # 指導教授資訊，提示 LLM 呈現順序時必須排最後
        "advisor_info": advisor_full,
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

    # 最終防線：無論 LLM 傳入的順序為何，強制確保指導教授排在委員名單最末位
    if student.advisor:
        advisor_full_submit = f"{student.advisor.professor_name} {student.advisor.professor_title} ({student.advisor.department_name})"
        # 尋找名單中是否有包含指導教授姓名的項目（容錯：格式可能略有不同）
        advisor_idx = next(
            (i for i, m in enumerate(final_committee_list)
             if student.advisor.professor_name in m),
            None
        )
        if advisor_idx is not None:
            # 已存在：移到最後
            final_committee_list.append(final_committee_list.pop(advisor_idx))
        else:
            # 不存在：補入最後（以資料庫標準格式）
            final_committee_list.append(advisor_full_submit)

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