#!/bin/bash

# auxiliary functions

function help() {
	echo -e "Usage:\n\t$(basename "$0") [-d/--dry-run] [--hook command] [-f/--force] <path>...\n\n  Rebuilds the metadata block of stills whose exif structure is damaged badly enough that\n  exiftool refuses to write them (\"Error reading OtherImageStart data in IFD0\" and friends),\n  which is what makes apto and pono give up on an asset.\n\n  Only files that fail a write probe are touched. --force rebuilds every file given, which\n  is lossy even on a healthy one: the embedded thumbnail, the MPF secondary images and any\n  vendor hdr gain map (Samsung AROT) do not survive the copy-back. Capture times, maker\n  notes, gps and the icc profile do."
}

# can exiftool rewrite this file's exif at all? there is no read-only tell — the structure
# only blows up while rebuilding the offsets chain — so probe with a real write aimed at a
# throwaway copy via -o, which leaves the source byte-identical. the probed tag has to live
# in an ifd: -Comment writes a jpeg com segment without touching ifd0 and passes on files
# that are plainly broken
function is_writable() {
	local src="$1" dir rc=1
	dir="$(mktemp -d)"
	exiftool -m -api QuickTimeUTC=1 -o "${dir}/probe.${src##*.}" \
		-CreateDate="2020:01:01 00:00:00" "${src}" >/dev/null 2>&1 &&
		[ -s "${dir}/probe.${src##*.}" ] && rc=0
	rm -rf "${dir}"
	return "${rc}"
}

# strip the metadata down and copy it back off the file's own tags, which drops whatever
# dangling pointer was making exiftool bail. icc_profile is named explicitly because
# -all:all leaves it behind, and losing it silently reinterprets a wide-gamut capture as
# srgb. the preview and thumbnail are deliberately not copied back: they are the unreadable
# part, and carrying them over would reinstate the damage
function rebuild_metadata() {
	exiftool -m -all= -tagsfromfile @ -all:all -icc_profile \
		--OtherImage:all --Preview:all -overwrite_original "$1"
}

# shell setup

set -euo pipefail

# arguments parsing

HOOK=""
DRY_RUN=0
FORCE=0
TARGETS=()
# stills only, on purpose: this repairs an ifd0 that points at preview data it cannot read,
# and containers without an ifd (mp4, mov, avi...) cannot get into that state. running an
# -all= wipe over a video would be a lossy no-op at best
EXTS=(
	arw
	dng
	heic
	jpeg
	jpg
	nef
	png
	webp
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
	-f | --force)
		FORCE=1
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

if [ "${#TARGETS[@]}" -eq 0 ]; then
	help
	exit 1
fi

# find runs inside a process substitution feeding fd 3, so its exit status is thrown away:
# without this a typo'd path is a silent success, and a caller driving tundo in a loop
# marks the asset repaired when nothing was ever looked at
for target in "${TARGETS[@]}"; do
	if [ ! -e "${target}" ]; then
		echo "No such path ${target}" >&2
		exit 1
	fi
done

# effective script

repaired=0
skipped=0
failed=0

exts="${EXTS[*]}"
exts="${exts// /|}"
while read -r fname <&3; do
	basename="$(basename "${fname}")"

	if [ "${FORCE}" = 0 ] && is_writable "${fname}"; then
		skipped="$((skipped + 1))"
		continue
	fi

	echo "Processing ${basename}..."
	if [ "${DRY_RUN}" = 1 ]; then
		echo "Would rebuild metadata for ${basename}"
		repaired="$((repaired + 1))"
		continue
	fi

	# fetch original modification time
	timestamp="$(date -r "${fname}" "+%Y%m%d%H%M.%S")"

	# perform the changes. the rebuild is checked by re-probing rather than by exiftool's own
	# exit status: it reports success for a copy-back that left the file just as unwritable
	if rebuild_metadata "${fname}" && is_writable "${fname}"; then
		touch -c -a -m -t "${timestamp}" "${fname}"
		repaired="$((repaired + 1))"
		echo "Rebuilt metadata for ${basename}"
	else
		failed="$((failed + 1))"
		echo "Can't rebuild metadata for ${basename}" >&2
		continue
	fi

	# run hook
	[ -z "${HOOK}" ] || "${HOOK}" "${fname}"
done 3< <(
	find "${TARGETS[@]}" -type f -not -name '.*' | grep -iE ".*.(${exts})$"
)

echo "Repaired ${repaired}, already writable ${skipped}, still broken ${failed}"
[ "${failed}" -eq 0 ]
