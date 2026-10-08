FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY replyforge ./replyforge
RUN pip install --no-cache-dir .
COPY config ./config
COPY examples ./examples
COPY templates ./templates
COPY static ./static
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations
RUN useradd -r -u 10001 replyforge
USER 10001
EXPOSE 8080
CMD ["uvicorn","replyforge.app:app","--host","0.0.0.0","--port","8080"]
