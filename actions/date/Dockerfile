FROM alpine:3.12
RUN apk add --update --no-cache coreutils bash
COPY entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
