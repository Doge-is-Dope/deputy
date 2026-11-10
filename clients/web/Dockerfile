# The page, built once and served with /api passed on to the runtime.
FROM node:24-slim AS build
COPY --from=oven/bun:1.4.4 /usr/local/bin/bun /usr/local/bin/bun
WORKDIR /web
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile
COPY . .
# Types are checked in CI: the tests they cover read fixtures from runtime/, outside this context.
RUN bun run vite build

FROM caddy:2.11.9-alpine
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /web/dist /srv
