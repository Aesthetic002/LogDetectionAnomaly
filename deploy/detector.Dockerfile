# Detector = ingest API + online pipeline + dashboard API + React page. Build context: repo root.
FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir drain3==0.9.11 numpy==2.4.6 pandas==3.0.6 pyarrow==26.0.0 scipy==1.17.1 \
    scikit-learn==1.9.1 fastapi==0.159.1 "uvicorn[standard]==0.54.0" httpx==0.28.1 pydantic==2.14.1 pyyaml
COPY src /app/src
COPY dashboard/react /app/dashboard/react
ENV PYTHONPATH=/app/src LOGPULSE_ROOT=/app PYTHONUNBUFFERED=1
EXPOSE 9000
CMD ["uvicorn", "logpulse.online.ingest_api:app", "--host", "0.0.0.0", "--port", "9000", "--log-level", "warning"]
