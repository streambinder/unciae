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

`--tz` is mandatory (e.g. `--tz +02:00`). The script will fail if not provided.
