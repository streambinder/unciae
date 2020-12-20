#!/bin/bash

# shellcheck source=./acl_common.sh
source "$(realpath "$(dirname "$0")")/acl_common.sh"

mkdir -p "${DIR_ACL}"
find "${DIR_ACL}" -type f -delete
getfacl -pR / > "/var/acls/root.acl" 2> /dev/null || echo -n