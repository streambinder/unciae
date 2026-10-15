# cano

This tool downloads a MuseScore sheet and assembles the pages of the sheet
into one PDF file. The pages stay vector graphics. The PDF page size is A4.

The tool uses the same internal API that the site viewer uses. A first fetch
of the score page collects the session cookies. The API refuses every later
request without the cookies of that first fetch. The tool then asks the API
for the signed address of each page and downloads the page as an SVG file.
The API signs an address for any index. A missing page reports 404 and marks
the end of the sheet.

## Caveats

The internal API of the site is not a public contract. A site update can
break the tool without notice. The signing suffix is part of the site client.
The site ships the suffix in clear text inside its public JavaScript bundle.

CairoSVG renders the SVG pages. CairoSVG needs the system Cairo library.
Debian and Ubuntu provide the library in the `libcairo2` package. macOS
provides the library through Homebrew with `brew install cairo`.

## How to use

```bash
uv run python main.py https://musescore.com/user/19710/scores/4766391
uv run python main.py <score-url> -o gymnopedie.pdf
```

The first form writes `<score id>.pdf` in the current directory. The tool
prints the page count and the output path on stderr.
