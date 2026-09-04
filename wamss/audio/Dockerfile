FROM node:22-alpine
WORKDIR /app
COPY protocol /app/protocol
COPY audio/package.json /app/package.json
COPY audio/src /app/src
EXPOSE 8787
CMD ["node", "src/server.mjs"]
