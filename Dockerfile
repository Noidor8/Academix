FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    ACADEMIX_DB=/data/academix.db \
    ACADEMIX_TELEGRAM_INBOX=/data/telegram-inbox.sqlite3

WORKDIR /app

COPY requirements-bot.txt ./
RUN python -m pip install --no-cache-dir -r requirements-bot.txt

RUN useradd --create-home --uid 10001 academix \
    && mkdir -p /data /app/.local \
    && chown academix:academix /data

COPY src/ ./src/

USER academix

CMD ["python", "-m", "academix.bot"]
