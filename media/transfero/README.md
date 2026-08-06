# Transfero

This script carries metadata over from an original media file onto its post-produced counterpart.

## How to use

Pass the original and the derivative to the runner:

```bash
transfero/main.sh path/to/original.jpg path/to/graded.jpg
```

The copy merges, it never wipes: whatever the derivative already holds and the
original does not — geotags written by `pono`, ratings, and the like — survives.

## Caveats

Orientation is reset to `1` rather than copied, since post-production suites bake
rotation into the pixels: an already upright image tagged `Rotate 90 CW` gets turned
sideways by every viewer.

The embedded thumbnail is regenerated off the derivative, as the original one
portraits the ungraded frame.

A handful of copied tags stop being true on the derivative — `Quality`,
`RAW File Type`, `File Format` and the Sony `HiddenDataOffset` pointer, which is
what makes `exiftool -validate` report a minor `Error reading HiddenData`. Cleaning
those up means hand-editing the maker notes block, which risks more than it fixes.

`InteropIndex` and `InteropVersion` cannot be carried over at all, being read-only
to exiftool, and `CompressedBitsPerPixel` is dropped on purpose, describing an
encoding the derivative no longer has.
