package main

import (
	"flag"
	"log"
	"math/rand"
	"strings"
	"time"

	spotitube "github.com/streambinder/spotitube/spotify"
	spotify "github.com/zmb3/spotify"
)

var argTimes int

func init() {
	rand.Seed(time.Now().UnixNano())
	flag.IntVar(&argTimes, "t", 1, "How many shufflings to do")
	flag.Parse()
}

func main() {
	if len(flag.Args()) == 0 {
		log.Fatal("At least a Spotify playlist URI is needed")
	}

	url := spotitube.BuildAuthURL("localhost")
	client, clientErr := spotitube.Auth(url.Full, "localhost", true)
	if clientErr != nil {
		log.Fatal(clientErr)
	}

	spotifyUser, spotifyUserID := client.User()
	log.Printf("Authenticated as %s (%s)", spotifyUser, spotifyUserID)

	for i := 0; i < argTimes; i++ {
		if argTimes > 1 {
			log.Printf("Shuffling round %d...", i+1)
		}

		for playlistCtr, playlistURI := range flag.Args() {
			playlistID := strings.Split(playlistURI, ":")[len(strings.Split(playlistURI, ":"))-1]

			p, err := client.Playlist(playlistURI)
			if err != nil {
				log.Printf("Playlist %d: %s\n", playlistCtr+1, err.Error())
				continue
			}

			if p.Owner.ID != spotifyUserID && !p.Collaborative {
				log.Printf("Playlist %s: no permissions over it\n", p.Name)
				continue
			}

			var (
				reorderedSlice  = indicesSlice(p.Tracks.Total, true)
				carbonCopySlice = indicesSlice(p.Tracks.Total, false)
			)
			for dstIndex, srcValue := range reorderedSlice {
				srcIndex := valueIndex(carbonCopySlice, srcValue)
				if _, err := client.ReorderPlaylistTracks(
					spotitube.ID(playlistID),
					spotify.PlaylistReorderOptions{
						RangeStart:   srcIndex,
						InsertBefore: dstIndex,
					}); err != nil {
					log.Printf("Playlist %s: %s\n", p.Name, err.Error())
				} else {
					carbonCopySlice = reorderSliceItem(carbonCopySlice, srcIndex, dstIndex)
				}
			}

			log.Printf("Playlist %s has been shuffled.", p.Name)
		}
	}
}

func valueIndex(slice []int, value int) int {
	for index, val := range slice {
		if val == value {
			return index
		}
	}
	return -1
}

func reorderSliceItem(slice []int, src, dst int) (ordered []int) {
	if src == dst {
		return slice
	}

	for index := range slice {
		switch index {
		case src:
			continue
		case dst:
			if src < dst {
				ordered = append(ordered, slice[index])
				ordered = append(ordered, slice[src])
			} else {
				ordered = append(ordered, slice[src])
				ordered = append(ordered, slice[index])
			}
		default:
			if index < len(slice) {
				ordered = append(ordered, slice[index])
			}
		}
	}
	return
}

func indicesSlice(length int, random bool) (slice []int) {
	for i := 0; i < length; i++ {
		slice = append(slice, i)
	}
	if random {
		rand.Shuffle(len(slice), func(i, j int) {
			slice[i], slice[j] = slice[j], slice[i]
		})
	}
	return
}
