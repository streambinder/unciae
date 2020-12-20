#!/bin/bash

# shellcheck disable=SC1090
source "$(realpath "$(dirname "$0")")/fw_common.sh"

"${IPTABLES_SAVE}" > "${FW_FNAME}"