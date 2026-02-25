import csv
import os
from sqlalchemy.orm import Session
import models
from database import SessionLocal, engine

# BASE_DIR 現在是 backend/
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 往上一層找到專案根目錄 defense-bot/
PROJECT_ROOT = os.path.dirname(BASE_DIR)
# 指向 defense-bot/data/
DATA_DIR = os.path.join(PROJECT_ROOT, "data")

PROFESSORS_CSV = os.path.join(DATA_DIR, "professors.csv")
STUDENTS_CSV = os.path.join(DATA_DIR, "students.csv")
# 若有地點資料，也可自行加入 LOCATIONS_CSV = ...

def run_seed():
    db = SessionLocal()
    try:
        print("🔍 啟動資料庫初始化程序...")
        
        # ==========================================
        # 1. 匯入教授資料 (順序很重要！必須先建教授，學生才能綁定指導教授)
        # ==========================================
        if os.path.exists(PROFESSORS_CSV):
            # 使用 utf-8-sig 可以過濾掉 Excel 存檔時可能產生的隱藏 BOM 字元
            with open(PROFESSORS_CSV, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # 檢查這名教授是否已經在資料庫裡了 (冪等性)
                    exists = db.query(models.Professor).filter_by(professor_id=row["professor_id"]).first()
                    if not exists:
                        db.add(models.Professor(**row))
            db.commit()
            print("✅ 教授資料 (professors.csv) 同步完成！")
        else:
            print(f"⚠️ 找不到教授名單：{PROFESSORS_CSV}")

        # ==========================================
        # 2. 匯入學生資料
        # ==========================================
        if os.path.exists(STUDENTS_CSV):
            with open(STUDENTS_CSV, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # 檢查這名學生是否已經在資料庫裡了 (冪等性)
                    exists = db.query(models.Student).filter_by(student_id=row["student_id"]).first()
                    if not exists:
                        db.add(models.Student(**row))
            db.commit()
            print("✅ 學生資料 (students.csv) 同步完成！")
        else:
            print(f"⚠️ 找不到學生名單：{STUDENTS_CSV}")

    except Exception as e:
        print(f"❌ CSV 資料匯入失敗，請檢查格式：{e}")
        db.rollback()
    finally:
        db.close()

# 單獨測試用
if __name__ == "__main__":
    models.Base.metadata.create_all(bind=engine)
    run_seed()