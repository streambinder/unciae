#!/usr/bin/env python3
"""Build-time patch for musegadget: answer the Muse identity on the local socket.

The shim must learn the attached Muse's name at startup to serve it
as its model, and the name lives behind GET /identity on the gateway
(proven reachable with the gadget credential: the identity probe
returns the name, tagline and vibe). The local socket has no generic
route call -- it only forwards turns ({"message": ...}) and opens
subscriptions ({"op": "subscribe_chat"}). This patch adds one more
operation to service.py only:

* A socket request with "op": "identity" asks the current session
  for GET /identity (LinkSession.request) and returns
  {"ok": true, "identity": {...}}. When the service is not connected
  yet, or the request fails, it answers {"ok": false, "error": ...}
  like every other local request failure.

It applies after patch_subscribe.py in the image build, so the
first needle matches the _handle_local text that patch leaves
behind (with its _wants_subscribe branch).

Fails the build loudly if upstream changes an expected line. An
optional first argument overrides the musegadget package directory
(for tests).
"""

import glob
import sys

SERVICE_PATCHES = [
    (
        """                if isinstance(request, dict) and request.get("op") == "subscribe_chat":
                    await self._local_subscribe(request, reader, writer)
                    return
                if self._wants_subscribe(line):
                    await self._local_stream_request(line, writer)
                    return
                reply = await self._local_request(line)
""",
        """                if isinstance(request, dict) and request.get("op") == "subscribe_chat":
                    await self._local_subscribe(request, reader, writer)
                    return
                if isinstance(request, dict) and request.get("op") == "identity":
                    reply = await self._local_identity()
                else:
                    if self._wants_subscribe(line):
                        await self._local_stream_request(line, writer)
                        return
                    reply = await self._local_request(line)
""",
    ),
    (
        "    async def _local_request(self, line: bytes) -> dict:\n",
        '''    async def _local_identity(self) -> dict:
        """Answer {"op": "identity"} with the attached Muse's identity.

        The shim asks for this once at startup to learn the Muse's
        name (GET /identity over the session's tunnel) and serve it
        as its model. The socket has no generic route call, so the
        service answers it here, like _local_request answers turns.
        """
        session = self._current
        if session is None or session.registered_at is None:
            return {"ok": False, "error": "not connected to the Muse"}
        try:
            result = await session.request("GET", "/identity")
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if not result.get("ok"):
            return {"ok": False,
                    "error": f"identity request failed (status {result.get('status')})"}
        identity = result.get("response")
        if not isinstance(identity, dict):
            return {"ok": False, "error": "identity is not an object"}
        return {"ok": True, "identity": identity}

    async def _local_request(self, line: bytes) -> dict:
''',
    ),
]


def patch_file(path: str, patches: list[tuple[str, str]]) -> None:
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    for needle, replacement in patches:
        if needle not in text:
            sys.exit(f"{path}: expected line not found; upstream changed, patch needs review")
        text = text.replace(needle, replacement, 1)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    print(f"patched {path}")


def main() -> None:
    if len(sys.argv) > 1:
        package_dirs = [sys.argv[1]]
    else:
        package_dirs = glob.glob("/opt/musegadget/venv/lib/python3.*/site-packages/musegadget")
    if len(package_dirs) != 1:
        sys.exit(f"musegadget package dir not found uniquely: {package_dirs}")
    patch_file(f"{package_dirs[0]}/service.py", SERVICE_PATCHES)


if __name__ == "__main__":
    main()
