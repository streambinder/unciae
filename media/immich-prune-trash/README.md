# immich-prune-trash

This tool deletes physical files of the external library which are currently in Immich trash,
prunes orphan assets (DB entries whose original file no longer exists on disk), and then
flushes the trash.

Orphan pruning is on by default: orphans are moved to the Immich trash via the API, and the
final empty-trash purges them for good. No raw SQL is used.

## Safety

Before touching anything, a mount guard verifies that the external libraries' import paths
are accessible on disk and that a sane fraction of sampled files actually exists. If the
storage looks unmounted or empty, the tool aborts instead of mass-deleting.

## How to use

```bash
immich-prune-trash [--no-prune-orphans] [--dry-run]
```

- `--no-prune-orphans`: skip orphan pruning; only delete on-disk originals of trashed assets.
- `--dry-run`: print what would be deleted/trashed without changing anything.
