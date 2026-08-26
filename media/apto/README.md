# Apto

This script enforces NAS media files compliance on sets of files (which can be checked with `consentio`).

## How to use

Pass a target path (which falls back to `$CWD`) to the runner:

```bash
apto/main.sh --tz +02:00 path/to/files
```

With `-e` (or `--exif`) flag, by default exif metadata will be used as source of truth:

```bash
apto/main.sh --exif --tz +02:00 path/to/files
```

`Create Date` is preferred, falling back to `Date/Time Original` when it is absent —
messenger exports and some re-encodes strip the former but keep the latter.

Conversely, with `-f` (or `--fs`) flag, FS timestamps will be used:

```bash
apto/main.sh --fs --tz +02:00 path/to/files
```

With `-n` (or `--name`) flag, the script will try to infer the date from filename:

```bash
apto/main.sh --name --tz +02:00 path/to/files
```

In some cases, `-s` (or `--smart`) flag might be useful as well, for letting the tool smartly decide:

```bash
apto/main.sh --smart --tz +02:00 path/to/files
```

With `--skip-compliant`, assets that already enforce compliance are skipped and kept as anchors:

```bash
apto/main.sh --exif --skip-compliant --tz +02:00 path/to/files
```

An asset is compliant when its EXIF capture time is set, its filename already follows the
enforced `YYYYMMDD-HHMMSS.ext` convention and its filesystem modification timestamp
matches the EXIF time. Compliant assets are left completely untouched — no rename, no
`touch`, no metadata rewrite — and pin their chronological slot: any file being renamed
onto an already taken timestamp is shifted a second forward, so skipped assets anchor
the sequencing of the rest of the pool.

`--tz` is mandatory (e.g. `--tz +02:00`). The script will fail if not provided.
