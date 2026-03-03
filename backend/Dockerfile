# ==========================================
# Defense-Bot Backend (uv + FastAPI)
# 適用於 GCP Cloud Run / Docker 本地部署
# ==========================================
FROM python:3.12-slim

# 安裝 uv（極速 Python 套件管理器）
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# 安裝系統依賴 (lxml / python-pptx 編譯需要)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

# 先複製依賴描述檔，利用 Docker 快取層
COPY pyproject.toml uv.lock* ./

# 用 uv 安裝依賴（不建立虛擬環境，直接裝到系統 Python）
RUN uv sync --frozen --no-dev --no-install-project

# 複製整個專案 (backend/ + data/ + templates/)
COPY backend/ ./backend/
COPY data/ ./data/
COPY templates/ ./templates/

# 建立下載目錄
RUN mkdir -p /app/backend/downloads

WORKDIR /app/backend

EXPOSE 8088

# GCP Cloud Run 會透過 PORT 環境變數指定埠號，預設 8088
CMD ["sh", "-c", "uv run uvicorn main:app --host 0.0.0.0 --port ${PORT:-8088}"]