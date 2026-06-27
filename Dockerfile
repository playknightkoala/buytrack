# Playwright 官方 Python 映像，已內含 Chromium 與系統依賴
FROM mcr.microsoft.com/playwright/python:v1.48.0-noble

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install chromium

COPY . .

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# 預設指令由 docker-compose 各服務覆寫
CMD ["python", "-m", "app.bot"]
