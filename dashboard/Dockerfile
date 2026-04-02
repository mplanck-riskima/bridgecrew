# Python runtime
FROM python:3.12-slim
WORKDIR /app

COPY dashboard/backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY dashboard/backend/ ./

EXPOSE 8000

# Note: Frontend dev server runs separately in docker-compose
# For production with bundled frontend, use a multi-stage build
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
