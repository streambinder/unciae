#!/bin/bash

# auxiliary functions

function help() {
    echo -e "Usage:\n\t$(basename "$0") <path> [-e/--exif|-f/--fs|-s/--smart]"
}

function install_media_file() {
    # check args
    src="$1"
    [ -z "${src}" ] && return 1
    dst="$2"
    [ -z "${dst}" ] && return 1

    # calculate shifts
    dst_dir="$(dirname "${dst}")"
    dst_base="$(basename "${dst}")"
    while [ -e "${dst_dir}/${dst_base}" ]; do
        echo "Shifting ${dst_base}"
        secs="${dst_base:13:2}"
        dst_base="${dst_base:0:13}$(expr "${secs}" + 1).${dst_base##*.}"
    done

    # install file
    mv -vn "${src}" "${dst_dir}/${dst_base}"
}

# shell setup

set -euo pipefail

# arguments parsing

MODE=interactive
TARGET=.
EXTS=(
    3gp
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

_modes=0
while [[ $# -gt 0 ]]; do
    case "$1" in
    -h | --help)
        help
        exit 0
        ;;
    -e | --exif)
        MODE=exif
        _modes=$(expr $_modes + 1)
        ;;
    -f | --fs)
        MODE=fs
        _modes=$(expr $_modes + 1)
        ;;
    -s | --smart)
        MODE=smart
        _modes=$(expr $_modes + 1)
        ;;
    *)
        TARGET="$1"
        ;;
    esac
    shift || echo -n
done

# arguments validation

if [ ${_modes} -gt 1 ]; then
    echo "--exif, --fs and --smart flags are mutually exclusive"
    exit 1
fi

# effective script

EXTS="${EXTS[@]}"
EXTS="${EXTS// /|}"
while read -r fname <&3; do
    dirname="$(dirname "${fname}")"
    basename="$(basename "${fname}")"
    echo "Processing ${basename}..."

    # parse timestamps
    exif_timestamps="$(exiftool -time:all "${fname}")"
    exif_create_date="$(awk -F': ' '/^Create Date  /{print $2}' <<< "${exif_timestamps}" | grep -v "0000:00:00" | awk -F'+' 'NR==1 {print $1}' || echo "9999:12:31 23:59:59")"
    fs_modification_time="$(awk -F': ' '/^File Modification Date\/Time  /{print $2}' <<< "${exif_timestamps}" | awk -F'+' 'NR==1 {print $1}')"

    if [ "${MODE}" = "smart" ]; then
        # in smart mode, let's sort it by picking the older timestamp
        [ ${fs_modification_time//[!0-9]/} -lt ${exif_create_date//[!0-9]/} ] && strategy=fs || strategy=exif
        [ -z "${exif_create_date}" ] && strategy=fs
    elif [ "${MODE}" = "interactive" ]; then
        # in interactive mode, let's ask the user
        echo -n "Choose a date for ${basename}: [E] ${exif_create_date} or [f] ${fs_modification_time} or [i] input? "
        read -n1 choice
        echo
        case "${choice}" in
        [fF])
            strategy=fs
            ;;
        [iI])
            strategy=input
            echo -n "Input a date: "
            read t
            t="${t//[!0-9]/}"
            input_timestamp="${t:0:4}:${t:4:2}:${t:6:2} ${t:8:2}:${t:10:2}:${t:12:2}"
            ;;
        *)
            strategy=exif
            ;;
        esac
    else
        strategy="${MODE}"
    fi

    # choose the timestamp
    if [ "${strategy}" = "exif" ]; then
        final_timestamp="${exif_create_date}"
    elif [ "${strategy}" = "fs" ]; then
        final_timestamp="${fs_modification_time}"
    else # input
        final_timestamp="${input_timestamp}"
    fi

    # compute timestamp formats
    final_exif_timestamp="${final_timestamp}"
    final_fs_timestamp="${fs_modification_time//[!0-9]/}"
    final_fs_timestamp="${final_fs_timestamp:0:12}"
    final_fname="${final_timestamp//:/}.${fname##*.}"
    final_fname="${final_fname/ /-}"

    # perform the changes
    exiftool -overwrite_original -wm w \
        -time:all="${final_exif_timestamp}" "${fname}" && \
    exiftool -overwrite_original \
        -CreateDate="${final_exif_timestamp}" \
        -DateTimeOriginal="${final_exif_timestamp}" \
        -MediaCreateDate="${final_exif_timestamp}" \
        -DateTime="${final_exif_timestamp}" "${fname}" && \
    touch -c -a -m -t "${final_fs_timestamp}" "${fname}" && \
    chmod 0644 "${fname}" && \
    install_media_file "${fname}" "${dirname}/${final_fname}"
done 3< <(
    find "${TARGET}" -type f -not -name '.*' | grep -iE ".*.($EXTS)$"
)
