# Pono

This script inflates media files with GPS coordinates for a given place.

## How to use

Pass an address to the runner:

```bash
pono/main.sh -a "Via Petroselli 50 00186 Roma" image.jpg
```

Or pass direct coordinates to skip geocoding:

```bash
pono/main.sh -a @41.9028,12.4964 image.jpg
```

The `-a` flag accepts either a place name (geocoded via OSM) or `@<lat>,<lon>` for direct positioning.
