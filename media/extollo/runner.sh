#!/bin/bash

# auxiliary functions

function help() {
	echo -e "Usage:\n\t$(basename "$0") -l <path/to/lut> <path>"
}

# shell setup

set -euo pipefail

# arguments parsing

LUT=""
TARGETS=()

while [[ $# -gt 0 ]]; do
	case "$1" in
	-h | --help)
		help
		exit 0
		;;
	-l | --lut)
		LUT="$2"
		shift || echo -n
		;;
	*)
		TARGETS+=("$1")
		;;
	esac
	shift || echo -n
done

# arguments validation

if [ -z "${LUT}" ]; then
	echo "A LUT file must be provided"
	exit 1
fi

# effective script

for fname in "${TARGETS[@]}"; do
	fname_ext="$(echo "${fname##*.}" | tr '[:upper:]' '[:lower:]' | sed 's/jpeg/jpg/g')"
	fname_tmp="/tmp/$(basename "${fname}").$$.${fname_ext}"

	if [ "${fname_ext}" == "jpg" ]; then
		gmic "${fname}" "${LUT}" 'map_clut[0]' '[1]' 'o[0]' "${fname_tmp}"
	elif [ "${fname_ext}" == "mp4" ]; then
		ffmpeg -nostdin -i "${fname}" -vf "lut3d=${LUT},mpdecimate,transpose=2" -c:v libx265 -vtag hvc1 -pix_fmt:v yuv420p -y "${fname_tmp}"
	else
		echo "Unsupported format ${fname_ext} at ${fname}"
		exit 1
	fi

	mv -vf "${fname_tmp}" "${fname}"
done
