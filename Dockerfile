FROM node:22-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends python3 && \
    ln -sf python3 /usr/bin/python && \
    rm -rf /var/lib/apt/lists/*

RUN corepack enable && corepack prepare pnpm@latest --activate

WORKDIR /app

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm run build

EXPOSE 3000

RUN chmod +x /app/start.sh
CMD ["/app/start.sh"]
