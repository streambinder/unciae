package main

import (
	"context"
	"flag"
	"log"
	"math/rand/v2"

	spotitube "github.com/streambinder/spotitube/spotify"
	spotify "github.com/zmb3/spotify/v2"
)

var (
	argTimes int
)

func init() {
	flag.IntVar(&argTimes, "t", 1, "How many shufflings to do")
	flag.Parse()
}

func main() {
	if len(flag.Args()) == 0 {
		log.Fatal("At least a Spotify playlist URI is needed")
	}

	client, err := spotitube.Authenticate(spotitube.BrowserProcessor)
	if err != nil {
		log.Fatal(err)
	}

	user, err := client.CurrentUser(context.Background())
	if err != nil {
		log.Fatal(err)
	}
	log.Printf("Authenticated as %s (%s)", user.DisplayName, user.ID)

	for i := 0; i < argTimes; i++ {
		if argTimes > 1 {
			log.Printf("Shuffling round %d...", i+1)
		}

		for i, arg := range flag.Args() {
			playlist, err := client.Playlist(arg)
			if err != nil {
				log.Printf("Playlist %d: %s\n", i+1, err.Error())
				continue
			}

			if playlist.Owner != user.ID && !playlist.Collaborative {
				log.Printf("Playlist %s: permission denied\n", playlist.Name)
				continue
			}

			var (
				reorderedSlice  = indicesSlice(len(playlist.Tracks), true)
				carbonCopySlice = indicesSlice(len(playlist.Tracks), false)
			)
			for dstIndex, srcValue := range reorderedSlice {
				srcIndex := valueIndex(carbonCopySlice, srcValue)
				if _, err := client.ReorderPlaylistTracks(
					context.Background(),
					spotify.ID(playlist.ID),
					spotify.PlaylistReorderOptions{
						RangeStart:   srcIndex,
						InsertBefore: dstIndex,
					}); err != nil {
					log.Printf("Playlist %s: %s\n", playlist.Name, err.Error())
				} else {
					carbonCopySlice = reorderSliceItem(carbonCopySlice, srcIndex, dstIndex)
				}
			}

			log.Printf("Playlist %s has been shuffled.", playlist.Name)
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
