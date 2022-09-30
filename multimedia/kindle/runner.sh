#!/usr/bin/env bash

set -eu
set -o pipefail

path="$1"
path_base="$(basename "${path}")"
path_tmp="/tmp/.$(basename "${path}" | md5sum | awk '{print $1}').$$"
title="$(awk -F' - ' '{print $1}' <<< "$(basename "${path}")" | sed 's/.pdf$//g')"
author="$(awk -F' - ' '{print $2}' <<< "$(basename "${path}")" | sed 's/.pdf$//g')"

gs -sDEVICE=pdfwrite -dCompatibilityLevel=1.4 \
	-dPDFSETTINGS=/screen -dNOPAUSE -dQUIET \
	-dDetectDuplicateImages -dCompressFonts=true -r150  \
	-dBATCH -sOutputFile="${path_tmp}" "${path}"
exiftool -Title="${title}" \
	-Author="${author}" \
	"${path_tmp}"
mv -vf "${path_tmp}" "${path}"
