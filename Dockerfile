# The control panel and watcher in a container, for a host such as Railway.
# Chrome is the real Google Chrome, as on a desktop, so pages render the same way.
FROM python:3.12-slim-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends wget ca-certificates procps \
 && wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
 && apt-get install -y --no-install-recommends /tmp/chrome.deb fonts-liberation \
 && rm -rf /tmp/chrome.deb /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENV HOST=0.0.0.0 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data

CMD ["sh", "start.sh"]
