#!/bin/bash

# auxiliary functions

function help() {
	echo -e "Usage:\n\t$(basename "$0")"
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
	esac
	shift
done

# arguments validation

# effective script

git rebase -i --root
git filter-branch --env-filter '
    GIT_COMMITTER_DATE=$GIT_AUTHOR_DATE;
    export GIT_COMMITTER_DATE'
