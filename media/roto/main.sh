#!/bin/bash

# auxiliary functions

function help() {
	echo -e "Usage:\n\t$(basename "$0") [--dry-run] [--encode] <90|180|270|flip|flop> [<path>...]"
}

# shell setup

set -euo pipefail

# arguments parsing

HOOK=""
TARGETS=()
DRY_RUN=0
ENCODE=0
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
	-e | --encode)
		ENCODE=1
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

# ffmpeg cannot edit in place, so encoded video lands here first. one scratch dir for the
# whole run, trapped: the old fixed /tmp/<basename> collided between concurrent runs and
# was trivially pre-planted by anyone else with write access to /tmp
SCRATCH="$(mktemp -d)"
trap 'rm -rf "${SCRATCH}"' EXIT

exts="${EXTS[*]}"
exts="${exts// /|}"
while read -r fname <&3; do
	basename="$(basename "${fname}")"
	echo "Processing ${basename}..."

	# build the invocation as an argv array. the previous string-and-eval form handed the
	# filename back to the parser as shell source, so a name carrying a paren aborted the
	# run outright and one carrying ; or $() executed as code
	encoded=""
	if [ "${ENCODE}" = 1 ]; then
		# gather media file type
		mime_type=$(file --mime-type -b "${fname}")
		if [[ "${mime_type}" == image/* ]]; then
			if [[ "${OP}" =~ ^[0-9]+$ ]]; then
				rotator=(mogrify -rotate "${OP}" "${fname}")
			else
				# dashed: mogrify reads a bare "flip" as a filename and dies on the decode
				rotator=(mogrify "-${OP}" "${fname}")
			fi
		elif [[ "${mime_type}" == video/* ]] || [[ "${mime_type}" == */octet-stream ]]; then
			case "${OP}" in
			90) filter="transpose=1" ;;
			180) filter="transpose=2,transpose=2" ;;
			270) filter="transpose=2" ;;
			flip) filter="vflip" ;;
			*) filter="hflip" ;;
			esac
			encoded="${SCRATCH}/${basename}"
			rotator=(ffmpeg -i "${fname}" -vf "${filter}" "${encoded}")
		else
			echo "${fname} has unknown type: skipping"
			continue
		fi
	else
		rotator=(exiftool "-rotation=${OP}" -overwrite_original -m "${fname}")
	fi

	# dry-run check. %q so a name holding spaces or parens is shown the way it would have
	# to be typed, rather than as something that looks copy-pasteable and is not
	if [ "${DRY_RUN}" = 1 ]; then
		echo "Command: $(printf '%q ' "${rotator[@]}")"
		continue
	fi

	# fetch original modification time
	timestamp="$(date -r "${fname}" "+%Y%m%d%H%M.%S")"

	# perform the changes
	"${rotator[@]}" &&
		{ [ -z "${encoded}" ] || mv -vf "${encoded}" "${fname}"; } &&
		touch -c -a -m -t "${timestamp}" "${fname}"

	# run hook
	[ -z "${HOOK}" ] || "${HOOK}" "${fname}"
done 3< <(
	find "${TARGETS[@]}" -type f -not -name '.*' | grep -iE ".*.(${exts})$"
)
