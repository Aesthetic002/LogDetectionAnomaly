# Fault injector with the Docker socket mounted. Build context: repo root.
FROM python:3.11-slim
WORKDIR /app/chaos
RUN pip install --no-cache-dir docker==7.2.0 fastapi==0.159.1 "uvicorn[standard]==0.54.0" httpx==0.28.1
ENV PYTHONUNBUFFERED=1
EXPOSE 9100
# chaos/ is bind-mounted at /app/chaos so ground_truth.csv lands in the repo
CMD ["uvicorn", "inject:app", "--host", "0.0.0.0", "--port", "9100", "--log-level", "warning"]
