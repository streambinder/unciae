#!/bin/bash

# auxiliary functions

function help() {
	echo -e "Usage:\n\t$(basename "$0") [-d/--dry-run] [--force] [--hook command] -a <address|@lat,lon> [<path>...]\n\n  Address can be a place name to geocode (e.g. \"Via Petroselli 50, Roma\") or direct coordinates\n  as @<lat>,<lon> (e.g. @41.9028,12.4964) to skip geocoding and use the given position directly.\n\n  By default GPS is written only to files lacking coordinates; files that already\n  carry them are skipped. --force overwrites existing coordinates as well."
}

# shell setup

set -euo pipefail

# arguments parsing

ADDRESS=""
HOOK=""
DRY_RUN=0
FORCE=0
TARGETS=()
EXTS=(
	3gp
	arw
	avi
	dng
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
	--force)
		FORCE=1
		;;
	-a | --address)
		ADDRESS="$2"
		shift || echo -n
		;;
	--hook)
		HOOK="$2"
		shift || echo -n
		;;
	*)
		TARGETS+=("$1")
		;;
	esac
	shift || echo -n
done

# arguments validation

if [ -z "${TARGETS[0]}" ] || [ -z "${ADDRESS}" ]; then
	help
	exit 1
fi

# effective script

if [ "${ADDRESS:0:1}" = "@" ]; then
	coords="${ADDRESS/@/}"
	latitude="$(awk -F',' '{print $1}' <<<"${coords}" | xargs)"
	longitude="$(awk -F',' '{print $2}' <<<"${coords}" | xargs)"
	name=""
	if [ "${DRY_RUN}" = 1 ]; then
		name="$(curl -s "https://nominatim.openstreetmap.org/reverse?format=json&lat=${latitude}&lon=${longitude}" | jq -r '.display_name')"
	fi
else
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
fi

if [ -n "${name}" ]; then
	echo "Found ${name}: lat ${latitude}, lon ${longitude}"
else
	echo "Using coordinates: lat ${latitude}, lon ${longitude}"
fi

[ "${DRY_RUN}" = 1 ] && exit 0

exts="${EXTS[*]}"
exts="${exts// /|}"

# write GPS to one file. Unless --force is given, files that already carry
# coordinates are left alone (-if guard); exiftool exits 2 for those.
function write_gps() {
	if [ "${FORCE}" = 1 ]; then
		exiftool -overwrite_original -m \
			-GPSPosition="${latitude},${longitude}" \
			-XMP:GPSLatitude="${latitude}" \
			-XMP:GPSLongitude="${longitude}" \
			"$1" || return $?
	else
		exiftool -overwrite_original -m -if "not \$GPSLatitude" \
			-GPSPosition="${latitude},${longitude}" \
			-XMP:GPSLatitude="${latitude}" \
			-XMP:GPSLongitude="${longitude}" \
			"$1" || return $?
	fi
}

FAILED=0
while read -r fname <&3; do
	basename="$(basename "${fname}")"
	echo "Processing ${basename}..."

	# fetch original modification time
	timestamp="$(date -r "${fname}" "+%Y%m%d%H%M.%S")"

	# perform the changes; a nonzero status must not abort the batch
	status=0
	write_gps "${fname}" || status=$?
	case "${status}" in
	0)
		touch -c -a -m -t "${timestamp}" "${fname}"
		;;
	2)
		echo "Skipped (already geotagged): ${basename}"
		;;
	*)
		echo "Failed to write ${basename}" >&2
		FAILED=1
		;;
	esac

	# run hook
	[ -z "${HOOK}" ] || "${HOOK}" "${fname}"
done 3< <(
	find "${TARGETS[@]}" -type f -not -name '.*' | grep -iE ".*.(${exts})$"
)

exit "${FAILED}"
