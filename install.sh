#!/bin/bash

NETWORK_NAME="defense-bot-net"
DIFY_DIR="./dify"

echo " 開始執行全本地一鍵部署..."

# 1. 建立共享網路
if [ -z "$(docker network ls | grep $NETWORK_NAME)" ]; then
    echo " 建立共享網路: $NETWORK_NAME..."
    docker network create $NETWORK_NAME
fi

# 2. 下載 Dify
if [ ! -d "$DIFY_DIR" ]; then
    echo " 正在下載 Dify..."
    git clone https://github.com/langgenius/dify.git $DIFY_DIR
fi

# 3. 設定並啟動 Dify
echo " 正在啟動 Dify 服務..."
cd $DIFY_DIR/docker
cp -n .env.example .env

# 讓 Dify 加入共享網路
cat <<EOF > docker-compose.override.yaml
version: '3'
networks:
  default:
    external:
      name: $NETWORK_NAME
EOF

docker compose up -d

# 4. 啟動後端
echo " 正在啟動 Python Backend..."
cd ../../
docker compose up -d --build

echo " 部署完成！"
echo " Backend API: http://localhost:8088/docs"