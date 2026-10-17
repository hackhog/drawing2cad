# Frontend der Demo-App (ADR 0010, 0012). Build-Kontext ist dieser Ordner:
#   docker compose build   bzw.   docker build app/frontend

# Stufe 1: React-Oberfläche → statische Dateien. Node ist nur hier nötig, nicht im fertigen Image.
FROM node:24.21.0-slim AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# Stufe 2: nginx ohne root-Rechte (Port 8080), liefert dist/ aus und leitet /api an das Backend weiter
FROM nginxinc/nginx-unprivileged:1.30.6-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist/ /usr/share/nginx/html/
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/ || exit 1
