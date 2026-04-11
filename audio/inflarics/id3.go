package main

import (
	"strings"

	"github.com/bogem/id3v2/v2"
	"github.com/streambinder/spotitube/lyrics"
)

const (
	frameSpotifyID = "Spotify ID"

	idUserDefinedText = "TXXX"
	langEnglish       = "eng"
)

type tag struct {
	*id3v2.Tag
	cache map[string]string
}

func openTag(path string, options id3v2.Options) (*tag, error) {
	rawTag, err := id3v2.Open(path, options)
	if err != nil {
		return nil, err
	}

	return &tag{
		Tag:   rawTag,
		cache: make(map[string]string),
	}, nil
}

func (tag *tag) SpotifyID() string {
	return tag.userDefinedText(frameSpotifyID)
}

func (tag *tag) SetLyrics(title, data string) {
	tag.AddUnsynchronisedLyricsFrame(id3v2.UnsynchronisedLyricsFrame{
		Encoding:          tag.DefaultEncoding(),
		Language:          langEnglish,
		ContentDescriptor: title,
		Lyrics:            lyrics.GetPlain(data),
	})
}

func (tag *tag) Close() error {
	if err := tag.Tag.Close(); err != nil && err != id3v2.ErrNoFile {
		return err
	}
	return nil
}

func (tag *tag) userDefinedText(key string) string {
	if value, ok := tag.cache[key]; ok {
		return value
	}

	for _, frame := range tag.GetFrames(idUserDefinedText) {
		userText, ok := frame.(id3v2.UserDefinedTextFrame)
		if !ok {
			continue
		}

		tag.cache[userText.Description] = userText.Value
		if strings.EqualFold(userText.Description, key) {
			return userText.Value
		}
	}

	return ""
}
