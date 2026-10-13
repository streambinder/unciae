#!/bin/sh
# Entrypoint for the limen container.
# Modes: run (default) | pair | info | send | <any musegadget subcommand>
set -eu

STATE_DIR="${MUSEGADGET_STATE_DIR:-/var/lib/musegadget}"
mkdir -p "$STATE_DIR" /run/musegadget
chmod 700 "$STATE_DIR" 2>/dev/null || true

# The SDK token arrives via env and is persisted where the musegadget
# service expects it: <state>/sdk_token.
if [ -n "${MUSEGADGET_SDK_TOKEN:-}" ]; then
	printf '%s' "$MUSEGADGET_SDK_TOKEN" >"$STATE_DIR/sdk_token"
	chmod 600 "$STATE_DIR/sdk_token"
	unset MUSEGADGET_SDK_TOKEN
fi

case "${1:-run}" in
pair)
	exec musegadget pair
	;;
run)
	# Shim in background; the gadget service is the main process.
	python3 /opt/shim/shim.py &
	exec musegadget run --run-as "${MUSEGADGET_RUN_AS:-gadget}"
	;;
info)
	exec musegadget info
	;;
send)
	shift
	exec musegadget send-user-msg "$@"
	;;
*)
	exec musegadget "$@"
	;;
esac
