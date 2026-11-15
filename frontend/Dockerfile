# syntax=docker/dockerfile:1
# Web app: the React build served by Caddy, which also proxies the API and WebSocket to the backend.
# HTTP on any address by default; automatic HTTPS only if GUARDIAN_SITE_ADDRESS is set to a domain (see Caddyfile).

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
