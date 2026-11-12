# The site, built as a standalone Next.js server. Build context: the repository root
# (`compose.yaml`). Pinned images, a non-root user, only the traced files at run time.
FROM node:22.22.1-bookworm-slim AS build
ENV NEXT_TELEMETRY_DISABLED=1 \
    COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN corepack enable pnpm
WORKDIR /src
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json ./
COPY apps/web/package.json apps/web/
COPY tools/api-types/package.json tools/api-types/
RUN pnpm install --frozen-lockfile --filter @match-analyzer/web
COPY apps/web/ apps/web/
# The relay from /api to the API is fixed when the site is built (next.config.ts).
ARG API_INTERNAL_URL=http://api:8000
ENV API_INTERNAL_URL=$API_INTERNAL_URL \
    NEXT_OUTPUT=standalone
RUN pnpm --filter @match-analyzer/web build

FROM node:22.22.1-bookworm-slim
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000
WORKDIR /app
COPY --from=build --chown=node:node /src/apps/web/.next/standalone ./
COPY --from=build --chown=node:node /src/apps/web/.next/static ./apps/web/.next/static
COPY --from=build --chown=node:node /src/apps/web/public ./apps/web/public
USER node
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
