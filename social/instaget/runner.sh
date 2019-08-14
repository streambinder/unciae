#!/bin/bash

# auxiliary functions

function help() { echo -e "Usage:\n\t$(basename $0) https://instagram.com/p/<ID>"; exit 0; }
function rprint() { echo -en "\r\e[0K$@"; }
function pprint() { echo -e "\r\e[0K$@"; }

# shell setup

# arguments parsing

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            help
            ;;
        *)
            TARGET=$1
            ;;
    esac
    shift
done

# arguments validation

if [ -z ${TARGET} ]; then
    help
fi

TARGET_ID="$(awk -F'/' '{print $NF}' <<< "${TARGET::-1}")"

if [ -z ${TARGET_ID} ]; then
    help
fi

TARGET_FNAME="${TARGET_ID}.jpg"

# effective script

rprint "Getting page data..."
target_page="$(curl -s "${TARGET}")"

rprint "Fetching asset URL..."
target_url="$(awk -F'content="' '/property="og:image"/ {print $2}' <<< "${target_page}" | awk -F'"' '{print $1}')"

if [ -z "${target_url}" ]; then
    pprint "Asset not found."
    exit 1
fi

rprint "Downloading asset..."
wget -q "${target_url}" -O "${TARGET_FNAME}"

if [ $? != 0 ]; then
    pprint "Unable to download asset."
    exit 1
fi

pprint "Asset downloaded at: ${TARGET_FNAME}"
