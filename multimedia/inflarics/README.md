# Inflarics

Inflarics is a tool to fetch and insert lyrics of tracks into MP3 files metadata.

## How to use

First of all export `GENIUS_TOKEN`:

```bash
# the following GENIUS_TOKEN is bogus
export GENIUS_TOKEN=XOLEQGXRSQRUPLVXPZRBOFACZBCPVDXPZHQOAMSYOCDGCIQUBSPLJFKNXBMJOYFL
```

Then, run the tool by path:
```bash
go run ./inflarics/runner.go \ 
    track.mp3 [-artist artist_name -title track_title]
```

Or, in the GOish way:

```bash
go get github.com/streambinder/nickels/multimedia/inflarics
inflarics track.mp3
```
