FROM node:22.23.1-bookworm-slim AS frontend-build

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
ARG ESAFE_BUILD_COMMIT=unknown
ENV VITE_ESAFE_BUILD_COMMIT=${ESAFE_BUILD_COMMIT}
RUN npm run build

FROM nginx:1.28-alpine

COPY infra/gateway/nginx.conf /etc/nginx/nginx.conf
COPY --from=frontend-build /app/dist /usr/share/nginx/html/live
COPY --from=frontend-build /app/dist /usr/share/nginx/html/demo
COPY --from=frontend-build /app/dist/assets /usr/share/nginx/html/assets

EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=4 \
  CMD wget --quiet --spider http://127.0.0.1:8080/health || exit 1
