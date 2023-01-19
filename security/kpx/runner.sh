#!/bin/bash

# auxiliary functions

function help() {
    echo -e "Usage:\n\t$(basename "$0") -k <path/to/key> -d <path/to/db> <name> [-l|-s]"
    exit 0
}
function rprint() { echo -en "\r\e[0K$*"; }
function pprint() { echo -e "\r\e[0K$*"; }

# shell setup

# arguments parsing

while [[ $# -gt 0 ]]; do
    case "$1" in
    -h | --help)
        help
        ;;
    -k | --key)
        KEY="$2"
        shift
        ;;
    -d | --db)
        DB="$2"
        shift
        ;;
    -u| --username)
        USERNAME=1
        ;;
    -l | --lookup)
        LOOKUP=1
        ;;
    -s | --show)
        SHOW=1
        ;;
    *)
        NAME=$1
        ;;
    esac
    shift
done

# arguments validation

if [ -z "${KEY}" ]; then
    KEY="${KPX_KEY}"
fi

if [ -z "${DB}" ]; then
    DB="${KPX_DB}"
fi

if [ -z "${KEY}" ] || [ -z "${DB}" ] || [ -z "${NAME}" ]; then
    help
fi

ATTR=password
if [ -n "${USERNAME}" ]; then
    ATTR=username
fi

# effective script

if [ -n "${LOOKUP}" ]; then
    keepassxc-cli locate -k "${KEY}" "${DB}" "$NAME"
elif [ -n "${SHOW}" ]; then
    keepassxc-cli show -s -k "${KEY}" "${DB}" "$NAME"
else
    keepassxc-cli clip -a "${ATTR}" -k "${KEY}" "${DB}" "$NAME"
fi
