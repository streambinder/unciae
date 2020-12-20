#!/bin/bash

# shellcheck disable=SC1090
source "$(realpath "$(dirname "$0")")/acl_common.sh"

mkdir -p "${DIR_ACL}"
find "${DIR_ACL}" -type f -delete
getfacl -pR / > "/var/acls/root.acl" 2> /dev/null || echo -n