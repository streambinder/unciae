#!/bin/bash

# auxiliary functions

function help() {
	echo -e "Usage:\n\t$(basename "$0") old@committ.er new_committer_name:new@committ.er"
	exit 0
}
function rprint() { echo -en "\r\e[0K$*"; }
function pprint() { echo -e "\r\e[0K$*"; }

# shell setup

# arguments parsing

while [[ $# -gt 0 ]]; do
	case "$1" in
	-h | --help)
		help
		;;
	*)
		if [ -z "${COMMITTER_OLD}" ]; then
			COMMITTER_OLD=$1
		else
			COMMITTER_NEW=$1
		fi
		;;
	esac
	shift
done

# arguments validation

COMMITTER_NEW_NAME="$(awk -F':' '{print $1}' <<<"${COMMITTER_NEW}")"
COMMITTER_NEW_EMAIL="$(awk -F':' '{print $2}' <<<"${COMMITTER_NEW}")"

if [ -z "${COMMITTER_OLD}" ] || [ -z "${COMMITTER_NEW_NAME}" ] || [ -z "${COMMITTER_NEW_EMAIL}" ]; then
	help
fi

# effective script

git filter-branch --env-filter '
    GIT_COMMITTER_DATE=$GIT_AUTHOR_DATE;
    export GIT_COMMITTER_DATE
    if [ "$GIT_AUTHOR_EMAIL" = "'"${COMMITTER_OLD}"'" ]; then
        GIT_AUTHOR_NAME='"${COMMITTER_NEW_NAME}"';
        GIT_AUTHOR_EMAIL='"${COMMITTER_NEW_EMAIL}"';
        GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME";
        GIT_COMMITTER_EMAIL=$GIT_AUTHOR_EMAIL;
    fi' -- --all
