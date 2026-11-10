FROM node:22-bookworm-slim AS miniapp
WORKDIR /build
COPY miniapp/package*.json ./
RUN npm ci
COPY miniapp/ ./
RUN npm run build

FROM python:3.12-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app
COPY --from=miniapp /build/dist /app/miniapp/dist
COPY --from=miniapp /build/dist-room /app/miniapp/dist-room
COPY --from=miniapp /usr/local/bin/node /usr/local/bin/node
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 && rm -rf /var/lib/apt/lists/* && node --version

CMD ["python", "main.py"]


