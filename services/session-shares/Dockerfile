FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEEPSEEK_SHARE_DIR=/data

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . \
    && useradd --uid 10001 --create-home shares \
    && mkdir /data \
    && chown shares:shares /data

USER shares
EXPOSE 8787
CMD ["python", "-m", "uvicorn", "deepseek_tui.server.share_service:create_app", "--factory", "--host", "0.0.0.0", "--port", "8787", "--no-access-log"]
