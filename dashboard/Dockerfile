# Next.js standalone Docker build
# Requires output: "standalone" in next.config.ts (already set).
#
# Build arg NEXT_PUBLIC_API_URL is baked into client bundles at build time.
# Keep it as http://localhost:8000 (the host machine port) because all browser
# requests go through the same-origin /api/backend proxy in lib/api.ts —
# the browser never calls the FastAPI directly.
#
# Runtime env API_INTERNAL_URL=http://api:8000 (set in docker-compose) is used
# by server-side Next.js API routes (app/api/backend/[...path]/route.ts) to
# proxy requests to the FastAPI container using the Docker service name.

# ── Stage 1: install deps ──────────────────────────────────────────────────
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# ── Stage 2: build ────────────────────────────────────────────────────────
FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Bake NEXT_PUBLIC_API_URL into client bundles.
# For Docker: browser uses same-origin /api/backend proxy, so this value is
# only a fallback. http://localhost:8000 = the host machine in a browser.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

RUN npm run build

# ── Stage 3: minimal runtime image ────────────────────────────────────────
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

# standalone output bundles server.js + all dependencies — no node_modules needed
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

EXPOSE 3000

# API_INTERNAL_URL is set at runtime by docker-compose environment: block.
# It is read by app/api/backend/[...path]/route.ts for server-side proxying.
CMD ["node", "server.js"]
