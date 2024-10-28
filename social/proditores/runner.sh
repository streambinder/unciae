#!/bin/bash

# auxiliary functions

function help() {
	echo -e "Usage:\n\t$(basename "$0") <path/to/file.zip|path/to/dir>"
	exit 0
}
function rprint() {
	printf '\r%*s' "$(tput cols)" " "
	echo -en "\r$*\r"
	[ -z "${NO_SLEEP}" ] && sleep .15
}
function pprint() {
	NO_SLEEP=0 rprint "$@"
	echo
}

# shell setup

# arguments parsing

while [[ $# -gt 0 ]]; do
	case "$1" in
	-h | --help)
		help
		;;
	*)
		TARGET=$1
		;;
	esac
	shift
done

# arguments validation

if [ -z "${TARGET}" ]; then
	help
fi

# effective script

rprint "Checking data file type..."
if [[ "${TARGET}" == *.zip ]]; then
	tmp_path="/tmp/proditores-$$"
	mkdir -p "${tmp_path}"
	rprint "Extracting zip archive..."
	unzip -d "${tmp_path}" -qq "${TARGET}"
	TARGET="${tmp_path}"
fi

rprint "Locating following.json file..."
following_json="$(find "${TARGET}" -name following.json)"
[ -z "${following_json}" ] && pprint "Unable to locate following.json file" && exit 1

rprint "Locating followers_1.json file..."
followers_json="$(find "${TARGET}" -name followers_1.json)"
[ -z "${followers_json}" ] && pprint "Unable to locate followers_1.json file" && exit 1

rprint "Locating pending_follow_requests.json file..."
pending_json="$(find "${TARGET}" -name pending_follow_requests.json)"
[ -z "${pending_json}" ] && pprint "Unable to locate pending_follow_requests.json file" && exit 1

rprint "Locating blocked_profiles.json file..."
blocked_json="$(find "${TARGET}" -name blocked_profiles.json)"
[ -z "${blocked_json}" ] && rprint "Unable to locate blocked_profiles.json file: ignoring blocked accounts..."

rprint "Computing following accounts set from file..."
following="$(jq -r '.relationships_following[].string_list_data[].value' <"${following_json}" | sort -u)"

rprint "Computing followers accounts set from file..."
followers="$(jq -r '.[].string_list_data[].value' <"${followers_json}" | sort -u)"

rprint "Computing unfollowed back accounts set from followers and following..."
followers_x_following="$(diff -urN <(echo "${following}") <(echo "${followers}"))"

rprint "Computing pending accounts set from file..."
pending="$(jq -r '.relationships_follow_requests_sent[].string_list_data[].value' <"${pending_json}" | sort -u)"

rprint "Computing blocked accounts set from file..."
[ -n "${blocked_json}" ] && blocked="$(jq -r '.relationships_blocked_users[].string_list_data[].href' <"${blocked_json}" | sort -u)"

rprint "Pulling last run followers cache..."
cache_path="$(find "$HOME/.cache/proditores" -type f -name 'followers-*' 2>/dev/null | sort | tail -1)"

rprint "Dumping cache of current followers..."
mkdir -p "$HOME/.cache/proditores" && echo "${followers}" >"$HOME/.cache/proditores/followers-$(date +%s)"

if [ -n "${cache_path}" ]; then
	rprint "Computing unfollowed accounts set..."
	unfollowed="$(diff -urN "${cache_path}" <(echo "${followers}") | awk -F'-' '/^-/ {print $2}')"

	if [ -n "${unfollowed}" ]; then
		pprint "Proditores found for unfollowing:"
		echo "${unfollowed}" | xargs printf "\- https://instagram.com/%s\n"
		echo
	fi
fi

pprint "Proditores found for not following back:"
awk -F'-' '/^-/ {print $2}' <<<"${followers_x_following}" | xargs printf "\- https://instagram.com/%s\n"
echo

pprint "Proditores found for not accepting follow request:"
echo "${pending}" | xargs printf "\- https://instagram.com/%s\n"
echo

pprint "You are proditor for $(grep ^+ <<<"${followers_x_following}" | sort -u | wc -l | xargs) accounts."
if [ -n "${blocked_json}" ]; then
	echo "The following accounts are blocked:"
	echo "${blocked}" | xargs printf "\- %s\n"
fi
