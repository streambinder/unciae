# Immich

This folder contains a set of Python tools to help with the management of an Immich instance.
It was mostly necessary, since I'm running it with a read-only external library.

The reusable client lives in `api.py` (package name `immich`); each tool under
`album-assets/`, `prune-trash/`, `refresh-assets/` is its own uv project consuming the
client via a `[tool.uv.sources]` Git reference (per `unciae/ai/README.md` §21.6).

All tools read `IMMICH_API_BASE` (default `http://localhost:2283`) and `IMMICH_API_KEY`
from the environment.
