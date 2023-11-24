package main

import (
	"errors"
	"fmt"
	"log"

	"github.com/bogem/id3v2/v2"
	"github.com/gosimple/slug"
	"github.com/spf13/cobra"
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
			for _, path := range args {
				tag, err := id3.Open(path, id3v2.Options{Parse: true})
				if err != nil {
					return err
				}
				defer tag.Close()

				artist, _ := cmd.Flags().GetString("artist")
				artist = util.Fallback(artist, tag.Artist())
				if len(artist) == 0 {
					return errors.New("artist name is mandatory")
				}

				title, _ := cmd.Flags().GetString("title")
				title = util.Fallback(title, tag.Title())
				if len(artist) == 0 {
					return errors.New("track title is mandatory")
				}

				var (
					url, _ = cmd.Flags().GetString("url")
					uslt   string
				)
				if len(url) > 0 {
					log.Printf("Downloading lyrics from %s...\n", url)
					uslt, err = lyrics.Get(url)
				} else {
					log.Printf("Searching lyrics for %s by %s...\n", title, artist)
					uslt, err = lyrics.Search(&entity.Track{ID: util.Fallback(tag.SpotifyID(), fakeID(artist, title)), Title: title, Artists: []string{artist}})
				}
				if err != nil {
					return err
				}

				if len(uslt) == 0 {
					log.Printf("Lyrics not found\n")
					continue
				}
				log.Printf("Found: %s\n", util.Excerpt(uslt, 50))

				tag.SetUnsynchronizedLyrics(title, uslt)
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
	cmd.Execute()
}

func fakeID(artist, title string) string {
	return slug.Make(fmt.Sprintf("inflarics-%s-%s", artist, title))
}
