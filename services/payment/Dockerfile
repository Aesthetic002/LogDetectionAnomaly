# Build context: services/ (so the shared common/ package can be copied in)
FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi==0.115.6 uvicorn==0.32.1 httpx==0.28.1
COPY common /app/common
COPY payment/app.py /app/app.py
ARG LOG_VARIANT=v1
ENV LOG_VARIANT=${LOG_VARIANT}
ENV SERVICE_NAME=payment PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--log-level", "warning"]
