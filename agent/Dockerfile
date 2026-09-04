FROM node:22-alpine
RUN apk add --no-cache docker-cli docker-cli-compose
WORKDIR /app
COPY protocol /app/protocol
COPY agent/package.json /app/package.json
COPY agent/src /app/src
ENV WHICK_STATE_PATH=/var/lib/whick/runtime-state.json
CMD ["node", "src/main.mjs"]
