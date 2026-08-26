# immich-scan

This tool triggers a scan of the Immich external library covering a given
filesystem path, waits for the `library` job queue to drain, and optionally
runs a shell command on success.

## Caveats

The Immich API has no subpath-scoped scan: `POST /api/libraries/{id}/scan`
always walks every import path of the library. This CLI takes a path argument
only to **resolve which library to scan**, not to limit the scan scope.

The poller watches only the `library` queue. Downstream `metadataExtraction` /
`thumbnailGeneration` jobs may still be active when this CLI exits — that is
intentional, since the hook (typically an album-creator restart) only depends
on assets existing in the DB.

The `--hook` command is executed via `sh -c`, so shell quoting rules apply.

## How to use

```bash
immich-scan /raid/media/roll/2026-05_Malaga \
    --hook "systemctl restart immich-folder-album-creator.service"
```

Environment: reads `IMMICH_API_BASE` (default `http://localhost:2283`) and
`IMMICH_API_KEY`, same as sibling tools.
