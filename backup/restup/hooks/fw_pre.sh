#!/bin/bash

# shellcheck source=./fw_common.sh
source "$(realpath "$(dirname "$0")")/fw_common.sh"

"${IPTABLES_SAVE}" > "${FW_FNAME}"