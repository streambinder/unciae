# Reasize

This tool is a simple images batch resizer: it has been made to enforce a common image maximum resolution threshold over a directory content.
It basically gets an argument (e.g. `2048x128`), parse it as maximum width and height resolution, but it won't be applied at the same time. The tool will analyze the content of a directory, checking whether an image is larger than the maximum width threshold and only if it does not, it will check whether it's taller than the height threshold.
In any case, if the asset exceeds in any way, the tool will build a `mogrify` command to resize it keeping its ratio, lowering its width or its height.

## How to use

To resize all the images (by width, greater than) down to 2048px, just use the following:

```bash
reasize/runner.sh -t /path/to/images 2048x
```

In order to do the same over the height size:

```bash
reasize/runner.sh -t /path/to/images x2048
```

Finally, to apply resize in both directions:

```bash
reasize/runner.sh -t /path/to/images 1024x768
```

Omitting `-t`/`--target` flag will let the tool use the current working directory.