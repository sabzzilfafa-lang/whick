FROM nginx:1.27-alpine

RUN apk add --no-cache gettext

COPY remote-portal/nginx.conf /etc/nginx/conf.d/default.conf.template
COPY remote-portal/remote-portal-envsubst.sh /docker-entrypoint.d/20-remote-portal-envsubst.sh
RUN chmod +x /docker-entrypoint.d/20-remote-portal-envsubst.sh

COPY remote-portal/index.html remote-portal/manifest.webmanifest remote-portal/sw.js remote-portal/favicon.ico /usr/share/nginx/html/
COPY remote-portal/css/ /usr/share/nginx/html/css/
COPY remote-portal/js/ /usr/share/nginx/html/js/
COPY remote-portal/i18n/ /usr/share/nginx/html/i18n/
COPY remote-portal/icons/ /usr/share/nginx/html/icons/
# UI only — never bake player Python/API sources into the public portal
COPY remote/index.html remote/README.md /usr/share/nginx/html/v4/
COPY remote/css/ /usr/share/nginx/html/v4/css/
COPY remote/js/ /usr/share/nginx/html/v4/js/
COPY remote/img/ /usr/share/nginx/html/v4/img/
COPY remote/i18n/ /usr/share/nginx/html/v4/i18n/