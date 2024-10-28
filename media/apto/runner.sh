#!/bin/bash

# auxiliary functions

function help() {
	echo -e "Usage:\n\t$(basename "$0") <path> [-e/--exif|-f/--fs|-n/--name|-s/--smart]"
}

function install_media_file() {
	# check args
	src="${1//\.\//}"
	[ -z "${src}" ] && return 1
	dst="${2//\.\//}"
	[ -z "${dst}" ] && return 1
	# don't move if we already have a file in the right position
	[ "${src}" == "${dst}" ] && return 0

	# calculate shifts
	dst_dir="$(dirname "${dst}")"
	dst_base="$(basename "${dst}")"
	while [ -e "${dst_dir}/${dst_base}" ]; do
		echo "Shifting ${dst_base}"
		secs="$((10#${dst_base:13:2} + 1))"
		dst_base="${dst_base:0:13}$(printf %02d "${secs}").${dst_base##*.}"
		# don't if we already have a file in the right position
		[ "${src}" == "${dst_dir}/${dst_base}" ] && return 0
	done

	# install file
	mv -vn "${src}" "${dst_dir}/${dst_base}"
}

# shell setup

set -euo pipefail

# arguments parsing

MODE=interactive
TARGETS=()
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
UNKNOWN_DATE="$(date +'%Y:%m:%d %H:%M:%S')"

_modes=0
while [[ $# -gt 0 ]]; do
	case "$1" in
	-h | --help)
		help
		exit 0
		;;
	-e | --exif)
		MODE=exif
		_modes="$((_modes + 1))"
		;;
	-f | --fs)
		MODE=fs
		_modes="$((_modes + 1))"
		;;
	-n | --name)
		MODE=name
		_modes="$((_modes + 1))"
		;;
	-s | --smart)
		MODE=smart
		_modes="$((_modes + 1))"
		;;
	*)
		TARGETS+=("$1")
		;;
	esac
	shift || echo -n
done

# arguments validation

if [ "${_modes}" -gt 1 ]; then
	echo "--exif, --fs, --name and --smart flags are mutually exclusive"
	exit 1
fi

# effective script

exts="${EXTS[*]}"
exts="${exts// /|}"
while read -r fname <&3; do
	dirname="$(dirname "${fname}")"
	basename="$(basename "${fname}")"
	echo "Processing ${basename}..."

	# parse timestamps
	exif_timestamps="$(exiftool -time:all "${fname}")"
	exif_create_date="$(awk -F': ' '/^Create Date  /{print $2}' <<<"${exif_timestamps}" | grep -v "0000:00:00" | awk -F'+' 'NR==1 {print $1}' || echo "${UNKNOWN_DATE}")"
	[ "${#exif_create_date}" = 16 ] && exif_create_date="${exif_create_date}:00"
	fs_modification_time="$(awk -F': ' '/^File Modification Date\/Time  /{print $2}' <<<"${exif_timestamps}" | awk -F'+' 'NR==1 {print $1}')"
	name_date="${basename%.*}"
	name_date="${name_date//[!0-9]/}"
	name_date="${name_date:0:4}:${name_date:4:2}:${name_date:6:2} ${name_date:8:2}:${name_date:10:2}:${name_date:12:2}"
	[[ "${name_date}" =~ ^[0-9]{4}:[0-9]{2}:[0-9]{2}\ [0-2]{1}[0-9]{1}:[0-5]{1}[0-9]{1}:[0-5]{1}[0-9]{1}$ ]] || name_date="${UNKNOWN_DATE}"

	if [ "${MODE}" = "smart" ]; then
		# in smart mode, let's sort it by picking the older timestamp
		oldest="${name_date//[!0-9]/}"
		strategy="name"
		if [ "${fs_modification_time//[!0-9]/}" -lt "${oldest}" ]; then
			oldest="${fs_modification_time//[!0-9]/}"
			strategy="fs"
		fi
		if [ "${exif_create_date//[!0-9]/}" -lt "${oldest}" ]; then
			oldest="${exif_create_date//[!0-9]/}"
			strategy="exif"
		fi
		if [ "${oldest}" = "${UNKNOWN_DATE//[!0-9]/}" ]; then
			echo "Can't infer best timestamp to use for ${basename}: exiting"
			exit 1
		fi
	elif [ "${MODE}" = "interactive" ]; then
		# in interactive mode, let's ask the user
		echo -n "Choose a date for ${basename}: [E] ${exif_create_date} or [f] ${fs_modification_time} or [n] ${name_date} or [i] input? "
		read -rn1 choice
		echo
		case "${choice}" in
		[fF])
			strategy=fs
			;;
		[nN])
			strategy=name
			;;
		[iI])
			strategy=input
			echo -n "Input a date: "
			read -r t
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
	elif [ "${strategy}" = "name" ]; then
		final_timestamp="${name_date}"
	else # input
		final_timestamp="${input_timestamp}"
	fi
	echo "Chosen date: ${final_timestamp}"

	# compute timestamp formats
	final_exif_timestamp="${final_timestamp}"
	final_fs_timestamp="${final_timestamp//[!0-9]/}"
	final_fs_timestamp="${final_fs_timestamp:0:12}.${final_fs_timestamp:12:2}"
	final_ext="$(echo "${fname##*.}" | tr '[:upper:]' '[:lower:]' | sed 's/jpeg/jpg/')"
	final_fname="${final_timestamp//:/}.${final_ext}"
	final_fname="${final_fname/ /-}"

	# perform the changes
	exiftool -overwrite_original -wm w \
		-time:all="${final_exif_timestamp}" "${fname}" &&
		exiftool -overwrite_original \
			-CreateDate="${final_exif_timestamp}" \
			-DateTimeOriginal="${final_exif_timestamp}" \
			-MediaCreateDate="${final_exif_timestamp}" \
			-DateTime="${final_exif_timestamp}" "${fname}" &&
		touch -c -a -m -t "${final_fs_timestamp}" "${fname}" &&
		chmod 0644 "${fname}" &&
		install_media_file "${fname}" "${dirname}/${final_fname}"
done 3< <(
	find "${TARGETS[@]}" -type f -not -name '.*' | grep -iE ".*.(${exts})$"
)
