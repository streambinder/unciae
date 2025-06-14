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

for fname in "$@"; do
	dirname="$(readlink -f "$(dirname "${fname}")")"
	basename="$(basename "${fname}")"
	fullname="${dirname}/${basename}"
	echo "Processing ${basename} at ${dirname}..."

	echo -n "Fetching asset ID... "
	assets="$(curl_immich /search/metadata -d "{\"originalFileName\":\"${basename}\",\"originalPath\":\"${dirname}\"}")"
	asset_id="$(jq -r --arg f "${fullname}" '.assets.items[]|select(.originalPath == $f)|.id' <<<"${assets}")"
	if [ -z "${asset_id}" ]; then
		echo "FAIL"
		continue
	fi
	echo "${asset_id}"

	for job_name in refresh-metadata regenerate-thumbnail; do
		echo -n "Launching ${job_name} job... "
		curl_immich /assets/jobs -d "{\"assetIds\":[\"${asset_id}\"],\"name\":\"${job_name}\"}" -X POST
		echo "OK"
	done
done
