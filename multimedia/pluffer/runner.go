package main

import (
	"log"
	"math/rand"
	"os"
	"time"

	spotitube "github.com/streambinder/spotitube/src/spotify"
	spotify "github.com/zmb3/spotify"
)

func main() {
	if len(os.Args) == 1 {
		log.Fatal("At least a Spotify playlist URI is needed")
	}

	url := spotitube.BuildAuthURL("localhost")
	client, clientErr := spotitube.Auth(url.Full, "localhost", true)
	if clientErr != nil {
		log.Fatal(clientErr)
	}

	spotifyUser, spotifyUserID := client.User()
	log.Printf("Authenticated as %s (%s)", spotifyUser, spotifyUserID)

	for playlistID, playlistURI := range os.Args[1:] {
		p, err := client.Playlist(playlistURI)
		if err != nil {
			log.Printf("Playlist %d: %s\n", playlistID+1, err.Error())
			continue
		}

		if p.Owner.ID != spotifyUserID && !p.Collaborative {
			log.Printf("Playlist %s: no permissions over it\n", p.Name)
			continue
		}

		ctr := 0
		for true {
			if _, err := client.ReorderPlaylistTracks(spotitube.ID(playlistURI), spotify.PlaylistReorderOptions{
				RangeStart:   0,
				InsertBefore: randomInt(2, len(p.Tracks.Tracks)),
			}); err != nil {
				log.Printf("Playlist %s: %s\n", p.Name, err.Error())
			}

			if ctr++; ctr == len(p.Tracks.Tracks) {
				break
			}
		}

		log.Printf("Playlist %s has been shuffled.", p.Name)
	}
}

func randomInt(lowerbownd, upperbound int) int {
	rand.Seed(time.Now().UnixNano())
	return rand.Intn(upperbound-lowerbownd+1) + lowerbownd
}
