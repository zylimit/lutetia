# Stage 1: build the project dashboard SPA (web-ui/). Node and node_modules stay in this stage only.
# Pinned by digest (multi-arch index of node:24-slim). Upgrade: docker buildx imagetools inspect node:24-slim, copy the top "Digest:" here.
FROM node:24-slim@sha256:01d566e8d94d8c619591d78652babfccd3c6992a3dffa9ed5ab39e11cf6c70e9 AS web-ui
WORKDIR /web-ui
COPY web-ui/package.json web-ui/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web-ui/ ./
RUN npm run build

# Stage 2: runtime image (Python only). The SPA build is copied in as static files served under /app/.
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY lutetia ./lutetia
RUN pip install --no-cache-dir . && rm -rf /app/lutetia /app/build /app/lutetia.egg-info
COPY --from=web-ui /web-ui/dist /app/web-ui-dist
ENV STATE_DIR=/data/state
ENV WEB_UI_DIST=/app/web-ui-dist
VOLUME ["/data"]
EXPOSE 8080
CMD ["sh", "-c", "lutetia migrate && exec lutetia run"]
