# Stage 1: Build frontend
FROM node:22-alpine AS frontend-build
WORKDIR /app
COPY dashboard/frontend/package*.json ./
RUN npm ci
COPY dashboard/frontend/ ./
RUN npm run build

# Stage 2: Backend + serve bundled frontend
FROM python:3.12-slim
WORKDIR /app

COPY dashboard/backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY dashboard/backend/ ./
# Copy Vite build output to /app/static — FastAPI serves this automatically
COPY --from=frontend-build /app/dist ./static

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
