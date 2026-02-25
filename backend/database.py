import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# 確保 data 資料夾存在 (如果沒有的話自動建立)
DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../data"))
os.makedirs(DATA_DIR, exist_ok=True)

# 設定 SQLite 資料庫檔案路徑
SQLALCHEMY_DATABASE_URL = f"sqlite:///{os.path.join(DATA_DIR, 'defense.db')}"

# 建立資料庫引擎 (check_same_thread=False 是 SQLite 搭配 FastAPI 必設的參數)
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

# 建立 Session 工廠，用來與資料庫對話
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 建立 Base 類別，之後所有的資料表 Model 都會繼承它
Base = declarative_base()

# Dependency: 用來在 FastAPI 取得資料庫連線
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()