#!/bin/bash

# auxiliary functions

function help() {
    echo -e "Usage:\n\t$(basename "$0") [-r] [-t seconds] <tunnel_name:ip> <ip>..."
    exit 0
}
function rprint() { echo -en "\r\e[0K$*"; }
function pprint() { echo -e "\r\e[0K$*"; }

# shell setup

set +e

# arguments parsing

while [[ $# -gt 0 ]]; do
    case "$1" in
    -h | --help)
        help
        ;;
    -t | --timeout)
        TIMEOUT="$2"
        shift
        ;;
    -r | --reset)
        RESET="true"
        ;;
    *)
        TUNNELS="${TUNNELS} $1"
        ;;
    esac
    shift
done

# arguments validation

if [ -z "${TUNNELS}" ]; then
    echo "At least one tunnel have must be given"
    exit 1
fi

if [ -z "${TIMEOUT}" ]; then
    TIMEOUT=1
fi

# effective script

for tunnel in ${TUNNELS}; do

    # tunnel data parsing
    tunnel_name="${tunnel}"
    tunnel_rep="${tunnel}"
    if [[ "${tunnel}" == *":"* ]]; then
        tunnel_name="$(awk -F':' '{print $1}' <<<"${tunnel}")"
        tunnel_rep="$(awk -F':' '{print $2}' <<<"${tunnel}")"
    fi

    # tunnel check
    rprint "Checking tunnel ${tunnel_name} (timeout: ${TIMEOUT})..."
    if ping -q -i1 -c"${TIMEOUT}" "${tunnel_rep}" >/dev/null; then
        pprint "Tunnel ${tunnel_name} is up."
        continue
    fi

    # tunnel reset
    pprint "Tunnel ${tunnel_name} is down."
    if [ -z "${RESET}" ]; then
        continue
    fi
    if [ "${tunnel_name}" == "${tunnel_rep}" ]; then
        pprint "Cannot proceed to tunnel reset: I need tunnel name in order to do that."
        continue
    fi
    rprint "Flushing connection ($(date '+%Y-%m-%d %H:%M:%S'))..."

    if (
        ipsec down "${tunnel}"
        ipsec down "${tunnel}"
        ipsec down "${tunnel}"
        sleep 1
        ipsec up "${tunnel}"
    ) >/dev/null 2>&1; then
        pprint "Tunnel ${tunnel_name} has been reset."
    else
        pprint "Could not reset tunnel ${tunnel_name}!"
    fi

done
