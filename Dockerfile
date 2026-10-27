FROM python:3.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=5000 UPLOAD_DIR=/data/uploads
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 portfolio && useradd --uid 10001 --gid portfolio --create-home portfolio
RUN mkdir -p /data/uploads && chown -R portfolio:portfolio /data
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY --chown=portfolio:portfolio . .
USER portfolio
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/healthz', timeout=4)"
CMD ["sh", "-c", "flask --app app init-db && exec gunicorn --config gunicorn.conf.py run:app"]
