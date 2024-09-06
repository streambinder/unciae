#!/bin/bash

# auxiliary functions

function help() {
	echo -e "Usage:\n\t$(basename "$0") <MAX_WIDTHxMAX_HEIGHT> [-t <path>]"
	exit 0
}
function rprint() { echo -en "\r\e[0K$*"; }
function pprint() { echo -e "\r\e[0K$*"; }

# shell setup

# arguments parsing

while [[ $# -gt 0 ]]; do
	case "$1" in
	-h | --help)
		help
		;;
	-t | --target)
		TARGET="$2"
		shift
		;;
	*)
		SIZE=$1
		;;
	esac
	shift
done

# arguments validation

if [ -z "${TARGET}" ]; then
	TARGET="$(pwd)"
fi

if [ -z "${SIZE}" ]; then
	help
fi

SIZE_W="$(awk -F'x' '{print $1}' <<<"${SIZE,,}" | xargs)"
SIZE_H="$(awk -F'x' '{print $2}' <<<"${SIZE,,}" | xargs)"

if [ -z "${SIZE_W}" ] && [ -z "${SIZE_H}" ]; then
	echo "At least a resolution argument must be given"
	exit 1
fi

# effective script

find "${TARGET}" -type f -exec file {} \; | grep -o -P '^.+: \w+ image' | awk -F':' '{print $1}' | while read -r fname; do

	pname="${fname//${TARGET}\//}"
	rprint "Checking ${pname}"

	# get image data

	if ! img_data="$(exiftool "${fname}")"; then
		continue
	fi

	# get image resolution
	img_res_w="$(awk -F': ' '/^Image Width/ {print $2}' <<<"${img_data}" | xargs)"
	img_res_h="$(awk -F': ' '/^Image Height/ {print $2}' <<<"${img_data}" | xargs)"
	if [ -z "${img_res_w}" ] || [ -z "${img_res_h}" ]; then
		continue
	fi

	# calculate resize
	img_res=""
	if [ -n "${SIZE_W}" ] && [ "${img_res_w}" -gt "${SIZE_W}" ]; then
		img_res="${SIZE_W}x"
	fi
	if [ -n "${SIZE_H}" ] && [ -z "${img_res}" ] && [ "${img_res_h}" -gt "${SIZE_H}" ]; then
		img_res="x${SIZE_H}"
	fi

	# process resize
	if [ -n "${img_res}" ]; then
		pprint "Resizing ${pname} to ${img_res} from ${img_res_w}x${img_res_h} ($(du -sh "${fname}" | awk '{print $1}'))"
		mogrify -resize "${img_res}" "${fname}"
	fi

done

pprint "Done."
