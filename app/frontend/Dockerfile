# Demo frontend (ADR 0010, 0012). Use this directory as the build context.
#   docker compose build   or   docker build app/frontend

# Stage 1 builds the static UI. The runtime image does not need Node.js.
FROM node:24.21.0-slim AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# Stage 2 serves the UI and forwards API requests. nginx runs without root privileges.
FROM nginxinc/nginx-unprivileged:1.30.6-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist/ /usr/share/nginx/html/
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/ || exit 1
