# Apto

This script enforces NAS media files compliance on sets of files (which can be checked with `consentio`).

## How to use

Pass a target path (which falls back to `$CWD`) to the runner:

```bash
apto/runner.sh path/to/files
```

With `-e` (or `--exif`) flag, by default exif metadata will be used as source of truth:

```bash
apto/runner.sh --exif path/to/files
```

Conversely, with `-f` (or `--fs`) flag, FS timestamps will be used:

```bash
apto/runner.sh --fs path/to/files
```

With `-n` (or `--name`) flag, the script will try to infer the date from filename:

```bash
apto/runner.sh --name path/to/files
```

In some cases, `-s` (or `--smart`) flag might be useful as well, for letting the tool smartly decide:

```bash
apto/runner.sh --smart path/to/files
```
