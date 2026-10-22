# Build context: services/ (so the shared common/ package can be copied in)
FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi==0.115.6 uvicorn==0.32.1 httpx==0.28.1 asyncpg==0.30.0
COPY common /app/common
COPY inventory/app.py /app/app.py
ENV SERVICE_NAME=inventory PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--log-level", "warning"]
