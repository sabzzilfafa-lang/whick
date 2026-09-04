FROM node:22-alpine
WORKDIR /app
COPY protocol /app/protocol
COPY monitor/package.json /app/package.json
COPY monitor/src /app/src
CMD ["node", "src/main.mjs"]
