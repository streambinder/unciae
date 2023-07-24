package main

import (
	"log"
	"math"

	"github.com/spf13/cobra"
	util "github.com/streambinder/spotitube/util/cmd"
)

func main() {
	cmd := &cobra.Command{
		Use:   "volnorm",
		Short: "Reset audio file max volume",
		Args:  cobra.MinimumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			for _, path := range args {
				log.Printf("Parsing max_volume for %s...\n", path)
				volumeDelta, err := util.FFmpeg().VolumeDetect(path)
				if err != nil {
					return err
				}

				if volumeDelta > 0 {
					volumeDelta = 0 - volumeDelta
				} else {
					volumeDelta = math.Abs(volumeDelta)
				}
				log.Printf("Balancing by %.1f...\n", volumeDelta)
				if err := util.FFmpeg().VolumeAdd(path, volumeDelta); err != nil {
					return err
				}
			}
			return nil
		},
	}
	cmd.Execute()
}
