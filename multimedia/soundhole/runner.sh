#!/bin/bash

# auxiliary functions

function help() {
    echo -e "Usage:\n\t$(basename "$0") <output.mp3>"
    exit 0
}
function rprint() { echo -en "\r\e[0K$*"; }
function pprint() { echo -e "\r\e[0K$*"; }

# shell setup

sound_card="quack_sink"

function format_duration() {
    ((hours = ${1} / 3600))
    ((minutes = (${1} % 3600) / 60))
    ((seconds = ${1} % 60))
    printf "%02d:%02d:%02d\n" "${hours}" "${minutes}" "${seconds}"
}

# arguments parsing

while [[ $# -gt 0 ]]; do
    case "$1" in
    -h | --help)
        help
        ;;
    *)
        TARGET="$1"
        shift
        ;;
    esac
    shift
done

# arguments validation

if [ -z "${TARGET}" ]; then
    help
fi

# effective script

trap on_stop SIGINT
function on_stop() {
    rprint "Timestamping..."
    date_stop="$(date +%s)"

    rprint "Removing quack card(s)..."
    grep -e "index" -e "sink_name=" <<<"$(pacmd list-modules)" |
        grep -B1 "${sound_card}" |
        head -1 |
        grep -o -E "[0-9]+" |
        while read -r card; do
            rprint "Removing card ${card}..."
            pacmd unload-module "${card}"
        done

    if [ "$((date_stop - date_start))" -lt "1" ]; then
        pprint "Record is too short."
        exit 1
    fi

    rprint "Collecting waveform data..."
    waveform="$(ffprobe -f lavfi -i amovie="${TARGET}",astats=metadata=1:reset=1 \
        -show_entries frame=pkt_pts_time:frame_tags=lavfi.astats.Overall.RMS_level,lavfi.astats.1.RMS_level,lavfi.astats.2.RMS_level \
        -of csv=p=0 2>/dev/null |
        grep -E "^($(seq $((date_stop - date_start)) | xargs | sed 's/\s/|/g'))\.")"

    rprint "Trimming duration coordinates..."
    trim_start="$(grep -v '\-inf' <<<"${waveform}" |
        head -1 | awk -F'.' '{print $1}')"
    trim_stop="$(grep -v '\-inf' <<<"${waveform}" |
        tail -1 | awk -F'.' '{print $1}')"

    rprint "Trimming output file..."
    ffmpeg -i "${TARGET}" -ss "$(format_duration "${trim_start}")" -to "$(format_duration "${trim_stop}")" -c copy ."${TARGET}" >/dev/null 2>&1 &&
        mv -f ."${TARGET}" "${TARGET}"

    pprint "Recorded at ${TARGET} ($(format_duration $((trim_stop - trim_start))))."
}

rprint "Generating quack card..."
pacmd load-module module-null-sink sink_name="${sound_card}"

quack_card="$(grep -e "index:" -e "name:" <<<"$(pacmd list-sinks)" |
    grep -B1 "${sound_card}" |
    head -1 |
    grep -o -E "[0-9]+")"
rprint "Setting quack card ${quack_card} as default..."
pacmd set-default-sink "${quack_card}"

rprint "Redirecting inputs to quack card..."
pacmd list-sink-inputs |
    grep -e index: |
    grep -o -E "[0-9]+" |
    while read -r flow; do
        rprint "Redirecting input ${flow} to quack card..."
        pacmd move-sink-input "${flow}" "${quack_card}"
    done

rprint "Timestamping..."
date_start="$(date +%s)"

rprint "Recording... Press CTRL+C to stop."
parec -d "${sound_card}.monitor" | lame -r -V0 - "${TARGET}"
