#!/bin/bash

set -uo pipefail
shopt -s lastpipe

function human_size() {
	echo "$@" | awk '{split("B KB MB GB TB PB EB ZB YB", v); s=1; while ($1>1024 && s<9) {$1/=1024; s++} printf "%.2f%s", $1, v[s]}'
}

function curl_immich() {
	endpoint="$1"
	shift
	curl -sL "${IMMICH_API_BASE:-http://localhost:2283}/api/${endpoint}" \
		-H 'Content-Type: application/json' \
		-H 'Accept: application/json' \
		-H "x-api-key: ${IMMICH_API_KEY}"
	# shellcheck disable=SC2068
	$@
}

echo "Deleting originals on disk..."
now="$(date +"%Y-%m-%dT%H:%M:%S")"
size_total="0"
curl_immich /search/metadata -d "{\"trashedBefore\":\"${now}\",\"isOffline\":false}" |
	jq -r '.assets.items[].originalPath' |
	while read -r i; do
		if [ -f "$i" ]; then
			size="$(du -sb "$i" | awk '{print $1}')"
			echo "$(human_size "${size}") $i"
			rm -f "$i"
			size_total="$((size_total + size))"
		fi
	done
echo "$(human_size "${size_total}") saved on disk"
echo

echo "Emptying trash on Immich..."
curl_immich /trash/empty -X POST | jq -r 'select(.count != 0) | "unregistered \(.count) assets"'
