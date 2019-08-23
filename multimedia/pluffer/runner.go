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

		for _, order := range randomOrders(p) {
			if _, err := client.ReorderPlaylistTracks(spotitube.PlaylistID(playlistURI), order); err != nil {
				log.Printf("Playlist %s: %s\n", p.Name, err.Error())
			}
		}

		log.Printf("Playlist %s has been shuffled.", p.Name)
	}
}

func randomOrders(playlist *spotitube.Playlist) []spotify.PlaylistReorderOptions {
	var options = []spotify.PlaylistReorderOptions{}

	for index, position := range randomRange(len(playlist.Tracks.Tracks)) {
		options = append(options, spotify.PlaylistReorderOptions{
			RangeStart:   index,
			InsertBefore: position,
		})
	}

	return options
}

func randomRange(size int) []int {
	var (
		ctr = 0
		arr = []int{}
	)
	for true {
		if ctr == size {
			break
		}
		arr = append(arr, ctr)
		ctr++
	}

	rand.Seed(time.Now().UnixNano())
	rand.Shuffle(len(arr), func(i, j int) { arr[i], arr[j] = arr[j], arr[i] })

	return arr
}
