#!/bin/bash

# auxiliary functions

function help() {
    echo -e "Usage:\n\t$(basename $0) <device> [devices...] -c <contact>"
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
    -c | --contact)
        CONTACT="$2"
        shift
        ;;
    *)
        DISKS="${DISKS} $1"
        ;;
    esac
    shift
done

# arguments validation

if [ -z "${DISKS}" ]; then
    echo "At least one disk path must be given"
    help
fi

if [ -z "${CONTACT}" ]; then
    echo "At least one contact email must be given"
    help
fi
CONTACT_DOMAIN="$(awk -F'@' '{print $2}' <<<"${CONTACT}")"

# effective script

disk_scrub_log="/tmp/scrub-$$.log"
for disk in ${DISKS}; do
    cat <<EOF >${disk_scrub_log}
From: "Scrubber" <scrubber@${CONTACT_DOMAIN}>
To: <${CONTACT}>
Subject: BTRFS scrub

EOF
    btrfs scrub start -Bd "${disk}" >>"${disk_scrub_log}"
    curl -q --ssl-reqd --insecure \
        --url "${SMTP_URI}" \
        --user "${SMTP_USER}:${SMTP_PASS}" \
        --mail-from "scrubber@${CONTACT_DOMAIN}" \
        --mail-rcpt "${CONTACT}" \
        --upload-file "${disk_scrub_log}"
done
