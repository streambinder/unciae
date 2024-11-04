#!/bin/bash

# auxiliary functions

function help() {
	echo -e "Usage:\n\t$(basename "$0") <path>"
}

# shell setup

set -euo pipefail

# arguments parsing

TARGET=.
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
	*)
		TARGET="$1"
		;;
	esac
	shift || echo -n
done

# effective script

exts="${EXTS[*]}"
exts="${exts// /|}"
find "${TARGET}" -type f -not -name '.*' | grep -iE ".*.(${exts})$" | while read -r fname; do
	# check folder settings
	[ -f "$(dirname "${fname}")/.uncompliant" ] && continue

	# check naming convention YYYYMMDD-hhmmss
	stem="$(basename "${fname%.*}")"
	[[ "${stem}" =~ ^[0-9]{8}\-[0-9]{6}$ ]] || echo "fname=${fname} stem=${stem}"

	# check extension lowercase/reduced (e.g. jpeg to jpg)
	ext="$(echo "${fname##*.}" | tr '[:upper:]' '[:lower:]' | sed 's/jpeg/jpg/')"
	[[ "${ext}" == "${fname##*.}" ]] || echo "fname=${fname} ext=${ext}"

	# check permissions
	perm="$(stat -c %a "${fname}")"
	[[ "${perm}" == "644" ]] || echo "fname=${fname} perm=${perm}"

	# check timestamps
	exif_timestamps="$(exiftool -time:all "${fname}")"
	exif_create_date="$(awk -F': ' '/^Create Date  /{print $2}' <<<"${exif_timestamps}" | awk 'NR==1 {print $1}')"
	fs_modification_time="$(awk -F': ' '/^File Modification Date\/Time  /{print $2}' <<<"${exif_timestamps}" | awk 'NR==1 {print $1}')"
	[[ "${fs_modification_time}" == "${exif_create_date}" ]] || echo "fname=${fname} fst=${fs_modification_time} et=${exif_create_date}"
done
