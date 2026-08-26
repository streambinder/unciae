#!/bin/bash

# shellcheck disable=SC1090,SC1091
source "$(realpath "$(dirname "$0")")/db_common.sh"

[ -d "${DIR_DB}" ] && find "${DIR_DB}" -type f -delete
