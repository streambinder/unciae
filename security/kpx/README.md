# KPX

This is a simple wrapper of `keepassxc-cli clip|show|locate`.

## How to use

In order to copy to clipboard:

```bash
kpx -k path/to/key -d path/to/db name
```

Or using environment variables:
```bash
export KPX_KEY=path/to/key
export KPX_DB=path/to/db
kpx name
```

It supports `-u` flag to copy the username entry instead, `-s` to show the whole key entry and `-l` to lookup the database for entries.
