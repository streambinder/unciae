#!/bin/bash

# auxiliary functions

function help() {
	echo -e "Usage:\n\t$(basename "$0")"
	exit 0
}

# shell setup

set -euo pipefail

# effective script

cd "$(cd -- "$(dirname -- "$(readlink -f "${BASH_SOURCE[0]}")")" &>/dev/null && pwd)/../.."
prev_category=""
while IFS= read -r dir; do
	category="${dir%%/*}"
	name="${dir#*/}"

	if [ "${category}" != "${prev_category}" ]; then
		[ -n "${prev_category}" ] && echo
		echo "${category}"
		prev_category="${category}"
	fi

	caption=""
	[ -f "${dir}/README.md" ] && caption="$(sed '3q;d' "${dir}/README.md")"
	echo -e "\t$(tput bold)${name}$(tput sgr0)\n\t\t${caption}"
done < <(find . -mindepth 3 -maxdepth 3 -name 'main.*' -type f -not -path '*/.venv/*' | sed 's|^\./||' | xargs -n1 dirname | sort -u)
