FROM node:18-alpine AS builder
RUN npm config set registry https://registry.npmmirror.com
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM nginx:alpine
COPY docker/ubuntu-nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80
ENV TZ=Asia/Shanghai
# 用 127.0.0.1：busybox wget 会把 localhost 解析成 ::1，而 nginx 只监听 IPv4，会被误判为 unhealthy
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 CMD wget --no-verbose --tries=1 --spider http://127.0.0.1:80/ || exit 1
CMD ["nginx", "-g", "daemon off;"]
