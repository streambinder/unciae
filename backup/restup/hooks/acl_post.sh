#!/bin/bash

# shellcheck disable=SC1090,SC1091
source "$(realpath "$(dirname "$0")")/acl_common.sh"

[ -d "${DIR_ACL}" ] && find "${DIR_ACL}" -type f -delete
