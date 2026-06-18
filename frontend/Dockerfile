# Stage 1 — build the React app
FROM node:20-slim AS builder
WORKDIR /app
ARG VITE_TASK_POLL_INTERVAL_MS=2000
ENV VITE_TASK_POLL_INTERVAL_MS=${VITE_TASK_POLL_INTERVAL_MS}
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Stage 2 — serve with nginx
FROM nginx:alpine
RUN apk add --no-cache gettext
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/templates/default.conf.template
EXPOSE 80
CMD ["/bin/sh", "-c", "if [ \"${NGINX_ACCESS_LOG:-0}\" = \"1\" ]; then ACCESS_LOG_DIRECTIVE='access_log /var/log/nginx/access.log main;'; else ACCESS_LOG_DIRECTIVE='access_log off;'; fi; export ACCESS_LOG_DIRECTIVE; envsubst '$ACCESS_LOG_DIRECTIVE' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf; exec nginx -g 'daemon off;'"]
