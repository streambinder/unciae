#!/bin/bash

# auxiliary functions

function help() {
	echo -e "Usage:\n\t$(basename "$0") [--dry-run] <90|180|270|flip|flop> [<path>...]"
}

# shell setup

set -euo pipefail

# arguments parsing

HOOK=""
TARGETS=()
DRY_RUN=0
OP=""
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
	--hook)
		HOOK="$2"
		shift || echo -n
		;;
	*)
		if [ -z "${OP}" ]; then
			OP="$1"
		else
			TARGETS+=("$1")
		fi
		;;
	esac
	shift || echo -n
done

# arguments validation

if [ -z "${TARGETS[0]}" ]; then
	help
	exit 1
fi

if [[ "${OP}" != "90" && "${OP}" != "180" && "${OP}" != "270" && "${OP}" != "flip" && "${OP}" != "flop" ]]; then
	echo "Invalid operation ${OP}"
	help
	exit 1
fi

# effective script

exts="${EXTS[*]}"
exts="${exts// /|}"
while read -r fname <&3; do
	basename="$(basename "${fname}")"
	echo "Processing ${basename}..."

	# gather media file type
	mime_type=$(file --mime-type -b "${fname}")
	if [[ "${mime_type}" == image/* ]]; then
		if [[ "${OP}" =~ ^[0-9]+$ ]]; then
			mogrify_op="-rotate ${OP}"
		else
			mogrify_op="${OP}"
		fi
		rotator="mogrify ${mogrify_op} ${fname}"
	elif [[ "${mime_type}" == video/* ]]; then
		if [[ "${OP}" == "90" ]]; then
			ffmpeg_op="-vf 'transpose=1'"
		elif [[ "${OP}" == "180" ]]; then
			ffmpeg_op="-vf 'transpose=2,transpose=2'"
		elif [[ "${OP}" == "270" ]]; then
			ffmpeg_op="-vf 'transpose=2'"
		elif [[ "${OP}" == "flip" ]]; then
			ffmpeg_op="-vf vflip"
		else
			ffmpeg_op="-vf hflip"
		fi
		rotator="ffmpeg -i ${fname} ${ffmpeg_op} /tmp/${basename} && mv -vf /tmp/${basename} ${fname}"
	else
		echo "${fname} has unknown type: skipping"
		continue
	fi

	# dry-run check
	if [ "${DRY_RUN}" = 1 ]; then
		echo "Command: ${rotator}"
		continue
	fi

	# fetch original modification time
	timestamp="$(date -r "${fname}" "+%Y%m%d%H%M.%S")"

	# perform the changes
	eval "${rotator}" &&
		touch -c -a -m -t "${timestamp}" "${fname}"

	# run hook
	[ -z "${HOOK}" ] || "${HOOK}" "${fname}"
done 3< <(
	find "${TARGETS[@]}" -type f -not -name '.*' | grep -iE ".*.(${exts})$"
)
