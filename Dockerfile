FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# أدوات البناء + مكتبات MySQL (لو بتستخدم pymysql مش هتضر)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    pkg-config \
    default-libmysqlclient-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

RUN mkdir -p /app/instance /app/static/uploads

# non-root user (uid 1000 عشان صلاحيات الفولدرات المتمونتة)
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 4500

# --timeout 120 عشان الـ agent بيستنى Gemini و OCR
CMD ["sh", "-c", "exec gunicorn -w 4 --threads 8 --timeout 120 -b 0.0.0.0:4500 --log-level info --access-logfile - --error-logfile - app:app"]
