#!/bin/bash

# auxiliary functions

function help() {
	echo -e "Usage:\n\t$(basename "$0")"
	exit 0
}

# shell setup

set -euo pipefail

# effective script

cd "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)/../.."
for category in *; do
	[ -d "${category}" ] || continue

	echo "${category}"
	cd "${category}"
	for name in *; do
		caption="$(sed '3q;d' "${name}/README.md")"
		echo -e "\t$(tput bold)${name}$(tput sgr0)\n\t\t${caption}"
	done
	echo
	cd ..
done
