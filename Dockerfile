FROM python:3.12-slim

# Встановлюємо системні залежності для компіляції
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Спочатку копіюємо requirements, щоб Docker кешував встановлення
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

# Команда запуску (міграції + сервер)
CMD alembic upgrade head && gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000