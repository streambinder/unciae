#!/bin/bash

# auxiliary functions

function help() {
	echo -e "Usage:\n\t$(basename "$0") [-d/--dry-run] -a <address> [<path>...]"
}

# shell setup

set -euo pipefail

# arguments parsing

ADDRESS=""
DRY_RUN=0
TARGETS=()
EXTS=(
	3gp
	arw
	avi
	heic
	jpeg
	jpg
	m4v
	mov
	mp4
	nef
	png
	webp
	wmv
)

while [[ $# -gt 0 ]]; do
	case "$1" in
	-h | --help)
		help
		exit 0
		;;
	-d | --dry-run)
		DRY_RUN=1
		;;
	-a | --address)
		ADDRESS="$2"
		shift || echo -n
		;;
	*)
		TARGETS+=("$1")
		;;
	esac
	shift || echo -n
done

# arguments validation

if [ -z "${ADDRESS}" ]; then
	help
	exit 1
fi

# effective script

echo "Fetching coordinates for ${ADDRESS}..."
address_encoded="$(jq -rn --arg address "${ADDRESS}" '$address|@uri')"
osm_data="$(curl -s "https://nominatim.openstreetmap.org/search?format=json&q=${address_encoded}")"
osm_results="$(jq -r length <<<"${osm_data}")"
if [ "${osm_results}" -eq 0 ]; then
	echo "No results found."
	exit 1
elif [ "${osm_results}" -gt 1 ]; then
	echo "Query returned more than one result:"
	jq -r '.[]|("- " + .display_name)' <<<"${osm_data}"
	exit 1
fi

name="$(jq -r '.[0].display_name' <<<"${osm_data}")"
latitude="$(jq -r '.[0].lat' <<<"${osm_data}")"
longitude="$(jq -r '.[0].lon' <<<"${osm_data}")"
altitude=$(curl -s "https://api.open-elevation.com/api/v1/lookup?locations=${latitude},${longitude}" | jq -r '.results[0].elevation')
echo "Found ${name}: lat ${latitude}, lon ${longitude}, alt ${altitude}"

[ "${DRY_RUN}" = 1 ] && exit 0

exts="${EXTS[*]}"
exts="${exts// /|}"
while read -r fname <&3; do
	basename="$(basename "${fname}")"
	echo "Processing ${basename}..."

	# fetch original modification time
	timestamp="$(date -r "${fname}" "+%Y%m%d%H%M.%S")"

	# perform the changes
	exiftool -overwrite_original -m \
		-GPSLatitude\*="${latitude}" \
		-GPSLongitude\*="${longitude}" \
		-GPSAltitude\*="${altitude}" "${fname}" &&
		touch -c -a -m -t "${timestamp}" "${fname}"
done 3< <(
	find "${TARGETS[@]}" -type f -not -name '.*' | grep -iE ".*.(${exts})$"
)
