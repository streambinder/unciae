#!/bin/bash

# auxiliary functions

function help() {
	echo -e "Usage:\n\t$(basename "$0") <path> [-e/--exif|-f/--fs|-n/--name|-s/--smart|-t/--time] [-d/--dry-run] --tz <offset> [--skip-compliant] [--skip-failures]"
}

# strip a trailing subsec and/or +/-HH:MM offset off an exif datetime string
function strip_offset() {
	sed -E 's/(\.[0-9]+)?[+-][0-9]{2}:[0-9]{2}$//' <<<"$1"
}

# extract the trailing +/-HH:MM offset off an exif datetime string, empty if naive
function extract_offset() {
	grep -oE '[+-][0-9]{2}:[0-9]{2}$' <<<"$1" || true
}

# convert a +/-HH:MM (or +/-H) offset into signed minutes
function tz_to_minutes() {
	local off="$1" sign hour min
	sign="${off:0:1}"
	hour="$(awk -F: '{printf "%d",$1}' <<<"${off:1}")"
	min="$(awk -F: '{printf "%d",($2=="")?0:$2}' <<<"${off:1}")"
	local total=$((hour * 60 + min))
	[ "${sign}" = "-" ] && total=$((-total))
	echo "${total}"
}

# shift a "YYYY:MM:DD HH:MM:SS" wall-clock by a signed second delta, portably, in the
# given strftime format. the epoch round-trip runs pinned to utc: through a dst-observing
# local zone the parse and the format would use different offsets and quietly eat an hour
function shift_timestamp() {
	local ts="$1" delta_sec="$2" fmt="${3:-%Y:%m:%d %H:%M:%S}" epoch
	if date -j >/dev/null 2>&1; then # bsd/macos
		epoch="$(TZ=UTC date -j -f "%Y:%m:%d %H:%M:%S" "${ts}" +%s)"
		TZ=UTC date -j -r "$((epoch + delta_sec))" +"${fmt}"
	else # gnu/linux; date -d wants YYYY-MM-DD, so swap only the two date-part colons
		epoch="$(TZ=UTC date -d "$(sed 's/:/-/;s/:/-/' <<<"${ts}")" +%s)"
		TZ=UTC date -d "@$((epoch + delta_sec))" +"${fmt}"
	fi
}

function install_media_file() {
	# check args
	src="${1//\.\//}"
	[ -z "${src}" ] && return 1
	dst="${2//\.\//}"
	[ -z "${dst}" ] && return 1
	# don't move if we already have a file in the right position
	[ "${src}" == "${dst}" ] && return 0

	# calculate shifts. bumping the stem through the epoch carries minutes into hours
	# and hours into days, which hand-rolled digit arithmetic got wrong past 59s
	dst_dir="$(dirname "${dst}")"
	dst_base="$(basename "${dst}")"
	while [ -e "${dst_dir}/${dst_base}" ]; do
		echo "Shifting ${dst_base}"
		stem="${dst_base%.*}"
		dst_base="$(shift_timestamp \
			"${stem:0:4}:${stem:4:2}:${stem:6:2} ${stem:9:2}:${stem:11:2}:${stem:13:2}" \
			1 "%Y%m%d-%H%M%S").${dst_base##*.}"
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
DRY_RUN=0
SKIP_COMPLIANT=0
SKIP_FAILURES=0
TARGETS=()
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
UNKNOWN_DATE="$(date +'%Y:%m:%d %H:%M:%S')"
TIME=""
TARGET_TZ=""

_modes=0
while [[ $# -gt 0 ]]; do
	case "$1" in
	-h | --help)
		help
		exit 0
		;;
	-d | --dry-run)
		DRY_RUN=1
		;;
	--skip-compliant)
		SKIP_COMPLIANT=1
		;;
	--skip-failures)
		SKIP_FAILURES=1
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
	-t | --time)
		TIME="$2"
		MODE=static
		_modes="$((_modes + 1))"
		shift || echo -n
		;;
	--tz)
		TARGET_TZ="$2"
		shift || echo -n
		;;
	*)
		TARGETS+=("$1")
		;;
	esac
	shift || echo -n
done

# arguments validation

if [ -z "${TARGET_TZ}" ]; then
	echo "--tz is mandatory: provide timezone like +02:00 or -05:00" >&2
	exit 1
fi

if [ "${_modes}" -gt 1 ]; then
	echo "--exif, --fs, --name, --smart and --time flags are mutually exclusive"
	exit 1
fi

if [ "${DRY_RUN}" = 1 ] && [ "${MODE}" = "interactive" ]; then
	MODE=smart
fi

if [ "${MODE}" = "static" ]; then
	TIME="${TIME//[!0-9]/}"
	if [ "${#TIME}" -lt 8 ]; then
		echo "At least YYYY-MM-DD granularity must be given for --time (${TIME}): exiting"
		exit 1
	fi

	TIME="$(printf %-14d "${TIME}" | tr ' ' 0)"
	TIME="${TIME:0:4}:${TIME:4:2}:${TIME:6:2} ${TIME:8:2}:${TIME:10:2}:${TIME:12:2}"
	echo "Statically using time: ${TIME}"
fi

# normalize a raw +/-H[:MM] offset into canonical +/-HH:MM form
function normalize_tz() {
	local raw="$1" sign hour min
	sign="${raw:0:1}"
	if [ "${sign}" == "0" ]; then
		sign="+"
		raw="${sign}${raw}"
	fi
	if [ "${sign}" != "-" ] && [ "${sign}" != "+" ]; then
		echo "Timezone sign must be explicit (${raw}): exiting" >&2
		return 1
	fi
	hour="$(awk -F: '{printf "%02d",$1}' <<<"${raw:1}")"
	min="$(awk -F: '{printf "%d00",$2}' <<<"${raw:1}" | cut -c1-2)"
	echo "${sign}${hour}:${min}"
}

TARGET_TZ="$(normalize_tz "${TARGET_TZ}")" || exit 1

RE_EXCLUDE='!'
if [ "${SKIP_COMPLIANT}" = 1 ]; then
	RE_EXCLUDE=".*[0-9]{8}\-[0-2]{1}[0-9]{1}[0-5]{1}[0-9]{1}[0-5]{1}[0-9]{1}\..*"
fi

# effective script

exts="${EXTS[*]}"
exts="${exts// /|}"
while read -r fname <&3; do
	dirname="$(dirname "${fname}")"
	basename="$(basename "${fname}")"
	echo "Processing ${basename}..."

	final_timestamp="${TIME}"
	if [ "${MODE}" != "static" ]; then
		# parse timestamps. QuickTimeUTC makes exiftool expose mp4/mov dates (stored as utc
		# by spec) with an explicit offset instead of a naive value we'd misread as local
		exif_timestamps="$(exiftool -api QuickTimeUTC=1 -time:all "${fname}")"
		# the grep exits nonzero when a file carries no create date at all, which under
		# pipefail would take the whole run down with it
		exif_create_date_raw="$(awk -F': ' '/^Create Date  /{print $2}' <<<"${exif_timestamps}" | grep -v "0000:00:00" | head -1 || true)"
		exif_datetimeoriginal_raw="$(awk -F': ' '/^Date\/Time Original  /{print $2}' <<<"${exif_timestamps}" | grep -v "0000:00:00" | head -1 || true)"
		[ -z "${exif_create_date_raw}" ] && exif_create_date_raw="${exif_datetimeoriginal_raw}"
		exif_create_date="$(strip_offset "${exif_create_date_raw}")"
		[ -z "${exif_create_date}" ] && exif_create_date="${UNKNOWN_DATE}"
		[ "${#exif_create_date}" = 16 ] && exif_create_date="${exif_create_date}:00"
		fs_modification_time_raw="$(awk -F': ' '/^File Modification Date\/Time  /{print $2}' <<<"${exif_timestamps}" | head -1)"
		fs_modification_time="$(strip_offset "${fs_modification_time_raw}")"
		# the zone the exif clock was in: dedicated tag first, else whatever QuickTimeUTC
		# left on the date itself. empty means the capture time is naive and unanchored
		exif_offset="$(awk -F': ' '/^Offset Time Original  /{print $2; exit}/^Offset Time  /{print $2}' <<<"${exif_timestamps}" | head -1)"
		[ -z "${exif_offset}" ] && exif_offset="$(extract_offset "${exif_create_date_raw}")"
		name_date="${basename%.*}"
		name_date="${name_date//[!0-9]/}"
		name_date="${name_date:0:4}:${name_date:4:2}:${name_date:6:2} ${name_date:8:2}:${name_date:10:2}:${name_date:12:2}"
		[[ "${name_date}" =~ ^[0-9]{4}:[0-9]{2}:[0-9]{2}\ [0-2]{1}[0-9]{1}:[0-5]{1}[0-9]{1}:[0-5]{1}[0-9]{1}$ ]] || name_date="${UNKNOWN_DATE}"

		if [ "${MODE}" = "smart" ]; then
			# an exif capture time that declares its own zone is the only candidate we can
			# place on an absolute scale, so it wins outright. the others are naive digits
			# in unknown frames: fs mtimes come back mangled off fat cards and some phones
			# encode utc in the filename, which makes comparing them by value meaningless
			if [ -n "${exif_offset}" ] && [ "${exif_create_date}" != "${UNKNOWN_DATE}" ]; then
				strategy="exif"
			else
				# otherwise fall back to picking the older timestamp
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
					[ "${SKIP_FAILURES}" = 1 ] && continue || exit 1
				fi
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
	fi

	# reject if we aren't able to compute the right timestamp
	if [ "${final_timestamp}" = "${UNKNOWN_DATE}" ]; then
		echo "Can't compute the right best timestamp to use for ${basename}: exiting"
		[ "${SKIP_FAILURES}" = 1 ] && continue || exit 1
	fi

	# recompute the wall-clock to the target zone, but only when the source zone is
	# known, taken from whichever source won above: mixing frames (e.g. the exif offset
	# onto an fs timestamp) lands hours off, and a naive date that declares no zone at
	# all is ambiguous, so it gets relabelled rather than guessed at
	src_tz=""
	if [ "${MODE}" != "static" ]; then
		case "${strategy}" in
		exif)
			meta_offset="${exif_offset}"
			;;
		fs)
			meta_offset="$(extract_offset "${fs_modification_time_raw}")"
			;;
		*) # name and input are naive digits, there is nothing to infer a zone from
			meta_offset=""
			;;
		esac
		[ -n "${meta_offset}" ] && src_tz="$(normalize_tz "${meta_offset}")"
	fi
	if [ -n "${src_tz}" ]; then
		delta_min=$(($(tz_to_minutes "${TARGET_TZ}") - $(tz_to_minutes "${src_tz}")))
		if [ "${delta_min}" != 0 ]; then
			echo "Converting ${final_timestamp} by $((delta_min / 60))h$((delta_min % 60))m (${src_tz} -> ${TARGET_TZ})"
			final_timestamp="$(shift_timestamp "${final_timestamp}" "$((delta_min * 60))")"
		fi
	fi

	echo "Chosen date for ${fname}: ${final_timestamp}${TARGET_TZ}"
	[ "${DRY_RUN}" = 1 ] && continue

	# compute timestamp formats
	final_exif_timestamp="${final_timestamp}${TARGET_TZ}"
	final_fs_timestamp="${final_timestamp//[!0-9]/}"
	final_fs_timestamp="${final_fs_timestamp:0:12}.${final_fs_timestamp:12:2}"
	final_ext="$(echo "${fname##*.}" | tr '[:upper:]' '[:lower:]' | sed 's/jpeg/jpg/')"
	final_fname="${final_timestamp//:/}.${final_ext}"
	final_fname="${final_fname/ /-}"

	# perform the changes
	[[ "${final_ext}" != "jpg" ]] || exiftool -overwrite_original -m -trailer= "${fname}"
	exiftool -api QuickTimeUTC=1 -overwrite_original -m -wm w \
		-time:all="${final_exif_timestamp}" "${fname}" &&
		exiftool -api QuickTimeUTC=1 -overwrite_original -m \
			-CreateDate="${final_exif_timestamp}" \
			-DateTimeOriginal="${final_exif_timestamp}" \
			-MediaCreateDate="${final_exif_timestamp}" \
			-DateTime="${final_exif_timestamp}" "${fname}" &&
		touch -c -a -m -t "${final_fs_timestamp}" "${fname}" &&
		chmod 0644 "${fname}" &&
		install_media_file "${fname}" "${dirname}/${final_fname}"
done 3< <(
	if [[ "${OSTYPE}" == "darwin"* ]]; then
		find -E "${TARGETS[@]}" -type f -not -name '.*' -not -regex "${RE_EXCLUDE}" | grep -iE ".*.(${exts})$"
	else
		find "${TARGETS[@]}" -type f -not -name '.*' -regextype posix-egrep -not -regex "${RE_EXCLUDE}" | grep -iE ".*.(${exts})$"
	fi
)
