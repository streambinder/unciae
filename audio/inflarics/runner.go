package main

import (
	"bufio"
	"errors"
	"fmt"
	"log"
	"os"
	"time"

	"github.com/gosimple/slug"
	"github.com/spf13/cobra"
	"github.com/streambinder/id3v2-sylt"
	"github.com/streambinder/spotitube/entity"
	"github.com/streambinder/spotitube/entity/id3"
	"github.com/streambinder/spotitube/lyrics"
	"github.com/streambinder/spotitube/util"
)

func main() {
	cmd := &cobra.Command{
		Use:   "inflarics",
		Short: "Fetch and insert lyrics of tracks into MP3 files metadata",
		Args:  cobra.MinimumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			var uslt = getStdin()
			for _, path := range args {
				log.Printf("Processing %s...\n", path)
				tag, tagErr := id3.Open(path, id3v2.Options{Parse: true})
				if tagErr != nil {
					return tagErr
				}
				defer tag.Close()

				artist := util.Fallback(util.ErrWrap(tag.Artist())(cmd.Flags().GetString("artist")), tag.Artist())
				if len(artist) == 0 && len(uslt) == 0 {
					return errors.New("track artist is mandatory")
				}

				title := util.Fallback(util.ErrWrap(tag.Title())(cmd.Flags().GetString("title")), tag.Title())
				if len(title) == 0 && len(uslt) == 0 {
					return errors.New("track title is mandatory")
				}

				if len(uslt) == 0 {
					lyrics, lyricsErr := getLyrics(artist, title, util.ErrWrap("")(cmd.Flags().GetString("url")), tag)
					if lyricsErr != nil {
						return lyricsErr
					}
					uslt = lyrics
				}

				if len(uslt) == 0 {
					log.Printf("Lyrics not found\n")
					continue
				}
				log.Printf("Lyrics: %s\n", util.Excerpt(uslt, 50))

				tag.SetLyrics(title, uslt)
				if err := tag.Save(); err != nil {
					return err
				}
			}
			return nil
		},
	}
	cmd.Flags().StringP("artist", "a", "", "Artist name")
	cmd.Flags().StringP("title", "t", "", "Track title")
	cmd.Flags().StringP("url", "u", "", "Lyrics URL")
	if err := cmd.Execute(); err != nil {
		log.Fatal(err)
	}
}

func fakeID(artist, title string) string {
	return slug.Make(fmt.Sprintf("inflarics-%s-%s", artist, title))
}

func getStdin() string {
	var (
		uslt  string
		stdin = make(chan string)
	)
	go func() {
		scanner := bufio.NewScanner(os.Stdin)
		for scanner.Scan() {
			stdin <- scanner.Text()
		}
		close(stdin)
	}()
	select {
	case uslt = <-stdin:
		return uslt
	case <-time.After(100 * time.Millisecond):
		return ""
	}
}

func getLyrics(artist, title, url string, tag *id3.Tag) (string, error) {
	if len(url) == 0 {
		log.Printf("Searching lyrics for %s by %s...\n", title, artist)
		return lyrics.Search(&entity.Track{ID: util.Fallback(tag.SpotifyID(), fakeID(artist, title)), Title: title, Artists: []string{artist}})
	}

	log.Printf("Downloading lyrics from %s...\n", url)
	return lyrics.Get(url)
}
