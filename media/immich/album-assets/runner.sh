#!/bin/bash

set -uo pipefail
shopt -s lastpipe

# shellcheck disable=SC2068
function curl_immich() {
	endpoint="$1"
	shift
	curl -sL "${IMMICH_API_BASE:-http://localhost:2283}/api/${endpoint}" \
		-H 'Content-Type: application/json' \
		-H 'Accept: application/json' \
		-H "x-api-key: ${IMMICH_API_KEY}" \
		$@
}

for id in "$@"; do
	curl_immich "/albums/${id}" | jq -r '.assets[].originalPath'
done
