FROM python:3.11-alpine

WORKDIR /app

RUN apk add --no-cache curl && \
    pip install --no-cache-dir requests fastapi uvicorn[standard]

COPY database.py checker_core.py epg.py app.py /app/
COPY requirements.txt /app/
COPY static/ /app/static/

RUN mkdir -p /data

EXPOSE 9239

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:9239/api/check_login || exit 1

ENTRYPOINT ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "9239"]
