# KPX

This is a simple wrapper of `keepassxc-cli`.

## How to use

```bash
kpx -k path/to/key -d path/to/db name
```

Or using environment variables:
```bash
export KPX_KEY=path/to/key
export KPX_DB=path/to/db
kpx name
```

It supports `-c` flag to copy password to clipboard temporarily.