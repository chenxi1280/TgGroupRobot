FROM node:22-alpine AS miniapp
WORKDIR /build
COPY miniapp/package*.json ./
RUN npm ci
COPY miniapp/ ./
RUN npm run build

FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app
COPY --from=miniapp /build/dist /app/miniapp/dist

CMD ["python", "main.py"]


