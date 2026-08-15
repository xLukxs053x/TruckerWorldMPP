FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN useradd --create-home --uid 10001 twmp
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py ./
COPY truckerworld_bot ./truckerworld_bot
RUN mkdir -p /app/data /app/logs && chown -R twmp:twmp /app

USER twmp
VOLUME ["/app/data", "/app/logs"]
CMD ["python", "main.py"]

