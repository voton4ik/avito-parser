FROM python:3.12-slim

# Системные зависимости для Playwright + Chromium
RUN apt-get update && apt-get install -y \
    wget curl gnupg ca-certificates \
    fonts-liberation libappindicator3-1 libasound2 libatk-bridge2.0-0 \
    libatk1.0-0 libcups2 libdbus-1-3 libgdk-pixbuf2.0-0 libgtk-3-0 \
    libnspr4 libnss3 libx11-xcb1 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libxss1 libxtst6 xdg-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Устанавливаем только Chromium (без Firefox и WebKit — экономим место)
RUN playwright install chromium
RUN playwright install-deps chromium

COPY . .

RUN mkdir -p logs data

CMD ["python", "parser.py"]
