FROM python:3.12-slim

WORKDIR /app

# 先装依赖，利用层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# SQLite 数据文件目录（由卷挂载持久化；启动时自动建库）
RUN mkdir -p /app/data
ENV DB_PATH=/app/data/deciders.db \
    HOST=0.0.0.0 \
    PORT=8000

EXPOSE 8000
VOLUME ["/app/data"]

# 启动时初始化数据库（FastAPI startup 自动执行）并运行服务
CMD ["sh", "-c", "uvicorn app.main:app --host ${HOST:-0.0.0.0} --port ${PORT:-8000}"]
