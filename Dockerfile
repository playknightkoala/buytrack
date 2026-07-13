# Playwright 官方 Python 映像，已內含 Chromium 與系統依賴
FROM mcr.microsoft.com/playwright/python:v1.48.0-noble

WORKDIR /app

# PDF 報告需要中日文字型（Chromium 渲染 HTML → PDF）
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install chromium

COPY . .

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# 預設指令由 docker-compose 各服務覆寫
CMD ["python", "-m", "app.bot"]
