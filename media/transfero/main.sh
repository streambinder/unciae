#!/bin/bash

# auxiliary functions

function help() {
	echo -e "Usage:\n\t$(basename "$0") <original> <derivative>"
}

# shell setup

set -euo pipefail

# arguments parsing

TARGETS=()

while [[ $# -gt 0 ]]; do
	case "$1" in
	-h | --help)
		help
		exit 0
		;;
	*)
		TARGETS+=("$1")
		;;
	esac
	shift || echo -n
done

# arguments validation

if [ "${#TARGETS[@]}" -ne 2 ]; then
	help
	exit 1
fi

ORIGINAL="${TARGETS[0]}"
DERIVATIVE="${TARGETS[1]}"

for fname in "${ORIGINAL}" "${DERIVATIVE}"; do
	if [ ! -f "${fname}" ]; then
		echo "No such file ${fname}"
		exit 1
	fi
done

# effective script

echo "Processing $(basename "${DERIVATIVE}")..."

# the original thumbnail portraits the ungraded frame, and on vertical shots it keeps the
# pre-rotation aspect ratio too: regenerate it off the derivative instead. -thumbnail over
# -resize: it drops the profiles as well, or the 160px jpeg would embed a copy of the whole
# exif and blow the 64kb app1 segment limit
thumbnail="/tmp/$(basename "${DERIVATIVE%.*}").$$.thumb.jpg"
trap 'rm -f "${thumbnail}"' EXIT
magick "${DERIVATIVE}" -thumbnail 160x160 -quality 70 "${thumbnail}"

# fetch original modification time
timestamp="$(date -r "${DERIVATIVE}" "+%Y%m%d%H%M.%S")"

# perform the changes. no -all= wipe beforehand: the derivative may hold metadata the
# original never had (geotags, ratings) and that has to survive. -m is what lets the copy
# through anyway, encoders like libavcodec leaving a tiff-style ifd0 behind whose
# stripoffsets point nowhere, which otherwise makes exiftool bail out while rebuilding the
# offsets chain. orientation is reset instead of copied, post-production baking rotation
# into the pixels: the hash suffix skips the print conversion, as a plain 1 would get
# substring-matched against "Rotate 180"
exiftool -overwrite_original -m \
	-tagsFromFile "${ORIGINAL}" -all:all --IFD1:all \
	-Orientation#=1 \
	-ThumbnailImage"<=${thumbnail}" \
	"${DERIVATIVE}" &&
	touch -c -a -m -t "${timestamp}" "${DERIVATIVE}"
