#!/bin/bash

# auxiliary functions

function help() {
    echo -e "Usage:\n\t$(basename "$0") <name>"
    exit 0
}

# shell setup

set -euo pipefail

# arguments parsing

while [[ $# -gt 0 ]]; do
    case "$1" in
    -h | --help)
        help
        ;;
    *)
        NAME="$1"
        ;;
    esac
    shift
done

# arguments validation

if [ -z "${NAME}" ]; then
    help
fi

# effective script

read -rs pass
echo "${pass}" | kpx "${NAME}" || \
    echo -e "${pass}\n${pass}" | salpass -c "${NAME}"
