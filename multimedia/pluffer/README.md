# Pluffer

Pluffer is a tool to batch shuffle tracks of Spotify playlists.

## How to use

First of all export `SPOTIFY_ID` and `SPOTIFY_KEY` environment keys:

```bash
# the following SPOTIFY_ID and SPOTIFY_KEY are bogus
export SPOTIFY_ID=YJ5U6TSB317572L40EMQQPVEI2HICXFL
export SPOTIFY_KEY=4SW2W3ICZ3DPY6NWC88UFJDBCZJAQA8J
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
