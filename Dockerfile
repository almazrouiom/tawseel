# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=production \
    DATA_DIR=/data \
    PORT=8000

WORKDIR /app

RUN groupadd --system tawseel && useradd --system --gid tawseel --create-home tawseel

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=tawseel:tawseel . .

RUN mkdir -p /data && chown -R tawseel:tawseel /data /app

USER tawseel

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "8", "--timeout", "120", "--access-logfile", "-", "wsgi:app"]
