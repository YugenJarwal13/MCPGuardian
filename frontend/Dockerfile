# syntax=docker/dockerfile:1
# Web app: the React build served by Caddy, which also proxies the API and WebSocket to the backend and
# obtains/renews the HTTPS certificate for $GUARDIAN_DOMAIN by itself.

FROM node:20-alpine AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM caddy:2-alpine
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /web/dist /srv
EXPOSE 80 443
