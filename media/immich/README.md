# Immich

Reusable Python client (`immich` package) wrapping the Immich REST API. Used by
the sibling tool projects `media/immich-album-assets/`, `media/immich-prune-trash/`,
`media/immich-refresh-assets/`, `media/immich-scan/`, which depend on it via a
`[tool.uv.sources]` Git reference (per `unciae/ai/README.md` §21.6).

All sibling tools read `IMMICH_API_BASE` (default `http://localhost:2283`) and
`IMMICH_API_KEY` from the environment.
