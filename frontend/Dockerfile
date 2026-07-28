FROM node:22-bookworm-slim AS dependencies
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts

FROM dependencies AS test
COPY frontend/ ./
RUN npm run verify

FROM dependencies AS build
ARG ESAFE_BUILD_COMMIT=unknown
ENV VITE_ESAFE_BUILD_COMMIT=${ESAFE_BUILD_COMMIT}
COPY frontend/ ./
RUN npm run build
