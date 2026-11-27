# syntax=docker/dockerfile:1.7
# Static SPA served by unprivileged nginx (runs as uid 101, listens on 8080),
# which also reverse-proxies /api to the backend so the browser sees one origin.

FROM --platform=$BUILDPLATFORM node:22-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.31.7-alpine3.24 AS runtime
LABEL org.opencontainers.image.source="https://github.com/sohumcs/specforge" \
      org.opencontainers.image.description="SPECForge web: React SPA + API reverse proxy"
ENV API_UPSTREAM=api:8000 \
    NGINX_ENVSUBST_FILTER=API_UPSTREAM
# Apply Alpine security fixes published after the base image was built
# (Trivy gates on fixable HIGH/CRITICAL), then drop back to the nginx user.
USER root
RUN apk upgrade --no-cache
USER 101
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY security-headers.conf /etc/nginx/security-headers.conf
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s CMD wget -qO- http://127.0.0.1:8080/nginx-health || exit 1
