# Small official Python image; slim keeps the build fast
FROM python:3.12-slim

WORKDIR /app

# Install deps first so Docker caches this layer when only code changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run injects PORT (usually 8080); default to 8080 for local docker runs
ENV PORT=8080
CMD exec uvicorn app:app --host 0.0.0.0 --port ${PORT}
