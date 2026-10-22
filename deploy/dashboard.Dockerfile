# Streamlit dashboard. Build context: repo root.
FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir streamlit==1.66.1 plotly==7.1.0 pandas==3.0.6 httpx==0.28.1 numpy==2.4.6
COPY dashboard /app/dashboard
ENV PYTHONUNBUFFERED=1
EXPOSE 8501
CMD ["streamlit", "run", "dashboard/app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
