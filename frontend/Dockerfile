FROM node:22-bookworm-slim AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY index.html vite.config.js ./
COPY src ./src
RUN npm run build -- --outDir /app/static \
    && test -f /app/static/index.html

FROM nginxinc/nginx-unprivileged:1.30.4-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/static /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["wget", "--quiet", "--output-document=-", "http://127.0.0.1:8080/healthz"]
