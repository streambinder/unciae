# Pluffer

Pluffer is a tool to batch shuffle tracks of Spotify playlists.

## How to use

First of all export `SPOTIFY_ID` and `SPOTIFY_KEY` environment keys:

```bash
# the following SPOTIFY_ID and SPOTIFY_KEY are bogus
export SPOTIFY_ID=REDACTED
export SPOTIFY_KEY=REDACTED
```

Then, run the tool by path:

```bash
go run ./pluffer/runner.go \
    spotify:playlist:$PL1 spotify:playlist:$PL2
```

Or, in the GOish way:

```bash
go get github.com/streambinder/nickels/multimedia/pluffer
pluffer spotify:playlist:$PL1 spotify:playlist:$PL2
```
