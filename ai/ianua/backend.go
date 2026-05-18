package main

import (
	"context"
	"strings"
)

// Backend is one CLI adapter. Implementations turn an OpenAI-style chat
// request into a CLI invocation and emit text deltas back over a channel.
type Backend interface {
	Name() string
	Models() []string
	// Stream sends incremental text deltas on the returned channel and closes
	// it when done. Errors surface via the error return on setup; mid-stream
	// failures close the channel early.
	Stream(ctx context.Context, req ChatRequest) (<-chan string, error)
}

// collapse messages into single prompt string. CLIs take one prompt;
// multi-turn history folded with role markers.
func collapseMessages(messages []ChatMessage) (system, prompt string) {
	var sys, buf strings.Builder
	for _, m := range messages {
		switch m.Role {
		case "system":
			if sys.Len() > 0 {
				sys.WriteString("\n\n")
			}
			sys.WriteString(m.Content)
		case "user":
			buf.WriteString("[USER]\n")
			buf.WriteString(m.Content)
			buf.WriteString("\n\n")
		case "assistant":
			buf.WriteString("[ASSISTANT]\n")
			buf.WriteString(m.Content)
			buf.WriteString("\n\n")
		}
	}
	return sys.String(), buf.String()
}
