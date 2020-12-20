#!/bin/bash

# auxiliary functions

function help() {
    echo -e "Usage:\n\t$(basename "$0") [-t seconds] <record>"
    exit 0
}

# shell setup

set +e

# arguments parsing

while [[ $# -gt 0 ]]; do
    case "$1" in
    -h | --help)
        help
        ;;
    -t | --timeout)
        TIMEOUT="$2"
        shift
        ;;
    *)
        RECORD="$1"
        ;;
    esac
    shift
done

# arguments validation

if [ -z "${TIMEOUT}" ]; then
    TIMEOUT=150
fi

if [ -z "${RECORD}" ]; then
    echo "At least one record name must be given"
    help
fi

DOMAIN="$(awk -F'.' '{print $(NF-1)"."$NF}' <<<"${RECORD}")"
if [ -z "${DOMAIN}" ]; then
    echo "Unable to reconstruct domain"
    exit 1
fi
RECORD="${RECORD/.${DOMAIN}/}"

if [ -z "${API_KEY}" ] || [ -z "${API_SECRET}" ]; then
    echo "Either API key or secret not exported"
    exit 1
fi

# effective script

echo "Getting latest public IP..."
public_ip="$(curl -s ifconfig.me)"
if [ -z "${public_ip}" ]; then
    echo "Unable to get latest public IP"
    exit 1
fi

echo "Setting ${RECORD} A record to ${public_ip}..."
if curl -f -s -X PUT "https://api.godaddy.com/v1/domains/${DOMAIN}/records/A/${RECORD}" \
    -H "Accept: application/json" \
    -H "Content-Type: application/json" \
    -H "Authorization: sso-key ${API_KEY}:${API_SECRET}" \
    --data '[{"data":"'"${public_ip}"'","name":"'"${RECORD}"'","ttl":3600,"type":"A"}]'; then
    echo "Record A for ${RECORD} succesfully updated to ${public_ip}"
else
    echo "Unable to update record A for ${RECORD} to ${public_ip}"
fi
