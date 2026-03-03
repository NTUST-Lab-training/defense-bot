#!/bin/bash
set -e

echo "🚀 Defense-Bot 後端一鍵部署 (Docker)"
echo "======================================"

# 0. 檢查 Docker 是否可用
if ! command -v docker &> /dev/null; then
    echo "❌ 找不到 Docker，請先安裝 Docker：https://docs.docker.com/get-docker/"
    exit 1
fi

if ! docker compose version &> /dev/null; then
    echo "❌ 找不到 Docker Compose，請確認 Docker 版本 >= 20.10"
    exit 1
fi

echo "✅ Docker 環境檢查通過"

# 1. 建立 .env（若不存在）
if [ ! -f .env ]; then
    echo "📝 偵測到尚未建立 .env，正在從範例檔複製..."
    cp .env.example .env
    echo "⚠️  請記得編輯 .env 填入 DIFY_API_KEY 與 SERVER_URL"
else
    echo "✅ .env 已存在，跳過"
fi

# 2. 建置並啟動後端容器
echo ""
echo "🔨 正在建置並啟動後端容器..."
docker compose up -d --build

echo ""
echo "======================================"
echo "✅ 部署完成！"
echo ""
echo "  📡 Backend API:  http://localhost:8088/docs"
echo ""
echo "  常用指令："
echo "    查看日誌:      docker compose logs -f"
echo "    停止服務:      docker compose down"
echo "    重新建置:      docker compose up -d --build"
echo "======================================"