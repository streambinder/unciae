#!/bin/bash

# auxiliary functions

function help() {
    echo -e "Usage:\n\t$(basename "$0")"
    exit 0
}
function rprint() { echo -en "\r\e[0K$*"; }
function pprint() { echo -e "\r\e[0K$*"; }

# effective script

dbus-send --system --print-reply --dest=org.bluez / org.freedesktop.DBus.ObjectManager.GetManagedObjects \
        | awk -F'"' '/\/(sep|fd)/ {print $2}' \
        | while read -r addr; do
    dbus-send --print-reply --system --dest=org.bluez "${addr}" \
        org.freedesktop.DBus.Properties.Set string:org.bluez.MediaTransport1 string:Volume variant:uint16:127
done