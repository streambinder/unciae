# Pluffer

Pluffer is a tool to batch shuffle tracks of a Spotify playlist.

## How to use

```bash
# the following SPOTIFY_ID and SPOTIFY_KEY are bogus
SPOTIFY_ID=YJ5U6TSB317572L40EMQQPVEI2HICXFL \
    SPOTIFY_KEY=4SW2W3ICZ3DPY6NWC88UFJDBCZJAQA8J \
    go run ./pluffer/runner.go spotify:playlist:$PLAYLIST_ID
```
