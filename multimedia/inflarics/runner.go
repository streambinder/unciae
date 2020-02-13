package main

import (
	"flag"
	"fmt"

	"github.com/bogem/id3v2"
	"github.com/sirupsen/logrus"
	"github.com/streambinder/spotitube/lyrics"
	"github.com/streambinder/spotitube/track"
)

var (
	argFilename string
	argArtist   string
	argTitle    string
	argVerbose  bool

	log *logrus.Logger
)

func init() {
	// logger setup
	log = logrus.New()

	// args parse
	flag.StringVar(&argArtist, "artist", "", "Artist name")
	flag.StringVar(&argTitle, "title", "", "Track title")
	flag.BoolVar(&argVerbose, "verbose", false, "Verbose mode")
	flag.Parse()

	if argVerbose {
		log.SetLevel(logrus.DebugLevel)
	}

	if len(flag.Args()) == 0 {
		log.Fatalln("At least a filename must be given")
	}

	argFilename = flag.Args()[0]
}

func main() {
	if argArtist == "" || argTitle == "" {
		artist, title, err := id3Parse(argFilename)
		if err != nil {
			log.WithError(err).Fatalln()
		}
		argArtist = artist
		argTitle = title
	}

	lyrics, err := fetchLyrics(argArtist, argTitle)
	if err != nil {
		log.WithError(err).Fatalln()
	}

	if err := id3Persist(argFilename, lyrics); err != nil {
		log.WithError(err).Fatalln()
	}

	log.Println("Track inflated.")
}

func id3Parse(filename string) (string, string, error) {
	track, err := track.OpenLocalTrack(filename)
	if err != nil {
		return "", "", err
	}

	return track.Artist, track.Title, nil
}

func id3Persist(filename, lyrics string) error {
	tag, err := id3v2.Open(filename, id3v2.Options{Parse: true})
	if err != nil {
		return err
	}
	defer tag.Close()
	defer tag.Save()

	tag.AddUnsynchronisedLyricsFrame(id3v2.UnsynchronisedLyricsFrame{
		Encoding:          id3v2.EncodingUTF8,
		Language:          "eng",
		ContentDescriptor: tag.Artist(),
		Lyrics:            lyrics,
	})

	return nil
}

func fetchLyrics(artist, title string) (string, error) {
	for _, p := range lyrics.All() {
		log.WithField("provider", p.Name()).Debugln("Searching lyrics...", p.Name())

		text, err := p.Query(argTitle, argArtist)
		if err != nil {
			log.WithError(err).Errorln()
			continue
		}

		return text, nil
	}

	return "", fmt.Errorf("Lyrics not found")
}
