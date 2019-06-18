#!/bin/bash

# auxiliary functions

function help() { echo -e "Usage:\n\t$(basename $0) <MAX_WIDTHxMAX_HEIGHT> [-t <path>]"; exit 0; }

# shell setup

# arguments parsing

while [[ $# -gt 0 ]]; do
	case "$1" in
		-h|--help)
			help
			;;
		-t|--target)
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

if [ -z ${TARGET} ]; then
	TARGET="$(pwd)"
fi

if [ -z ${SIZE} ]; then
	help
fi

SIZE_W="$(awk -F'x' '{print $1}' <<< "${SIZE,,}" | xargs)"
SIZE_H="$(awk -F'x' '{print $2}' <<< "${SIZE,,}" | xargs)"

if [ -z "${SIZE_W}" ] && [ -z "${SIZE_H}" ]; then
    echo "At least a resolution argument must be given"
    exit 1
fi

# effective script

find "${TARGET}" -type f | while read -r fname; do

    # get image data
    img_data="$(exiftool "${fname}")"
    if [ "$?" -ne 0 ]; then
        continue;
    fi

    # get image resolution
    img_res_w="$(awk -F': ' '/^Image Width/ {print $2}' <<< "${img_data}" | xargs)"
    img_res_h="$(awk -F': ' '/^Image Height/ {print $2}' <<< "${img_data}" | xargs)"
    if [ -z "${img_res_w}" ] || [ -z "${img_res_h}" ]; then
        continue;
    fi

    # calculate resize
    img_res=""
    if [ -n "${SIZE_W}" ] && [ "${img_res_w}" -gt "${SIZE_W}" ]; then
        img_res="${SIZE_W}x"
    fi
    if [ -n "${SIZE_H}" ] && [ "${img_res_h}" -gt "${SIZE_H}" ]; then
        img_res="x${SIZE_H}"
    fi

    # process resize
    if [ -n "${img_res}" ]; then
        echo "Resizing ${fname} to ${img_res} from ${img_res_w}x${img_res_h} ($(du -sh "${fname}" | awk '{print $1}'))"
        mogrify -resize "${img_res}" "${fname}"
    fi

done