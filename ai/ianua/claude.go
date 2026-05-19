package main

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"os"
	"os/exec"
	"strings"
)

type ClaudeBackend struct{}

func (ClaudeBackend) Name() string { return "claude" }

func (ClaudeBackend) Models() []string {
	return []string{"claude", "sonnet", "opus", "haiku"}
}

// claude stream-json event shape (only fields we care about).
type claudeEvent struct {
	Type    string `json:"type"`
	Message struct {
		Content []struct {
			Type string `json:"type"`
			Text string `json:"text"`
		} `json:"content"`
	} `json:"message"`
	Result string `json:"result"`
	Error  string `json:"error"`
}

// claude --effort accepts low|medium|high|xhigh|max. Anything else is
// silently dropped so a misconfigured client doesn't fail-close the request.
var claudeEffortLevels = map[string]struct{}{
	"low": {}, "medium": {}, "high": {}, "xhigh": {}, "max": {},
}

func claudeArgs(model, prompt, system, effort string) []string {
	args := []string{
		"-p", strings.TrimSpace(prompt),
		"--model", model,
		"--output-format", "stream-json",
		"--verbose",
		"--no-session-persistence",
	}
	if _, ok := claudeEffortLevels[effort]; ok {
		args = append(args, "--effort", effort)
	}
	if system != "" {
		args = append(args, "--system-prompt", system)
	}
	return args
}

// extract the concatenated text content from a single assistant event.
func eventText(ev claudeEvent) string {
	if ev.Type != "assistant" {
		return ""
	}
	var b strings.Builder
	for _, blk := range ev.Message.Content {
		if blk.Type == "text" {
			b.WriteString(blk.Text)
		}
	}
	return b.String()
}

// pumpStream reads claude NDJSON from r and emits incremental text deltas on
// out. claude emits cumulative message snapshots, so each emission is the
// suffix beyond what we've already sent.
func pumpStream(ctx context.Context, r io.Reader, out chan<- string) {
	scanner := bufio.NewScanner(r)
	// claude can emit long JSON lines (system init dump). Bump buffer.
	scanner.Buffer(make([]byte, 0, 64*1024), 4*1024*1024)

	var emitted string
	for scanner.Scan() {
		line := scanner.Bytes()
		if len(line) == 0 || line[0] != '{' {
			continue
		}
		var ev claudeEvent
		if json.Unmarshal(line, &ev) != nil {
			continue
		}
		full := eventText(ev)
		if full == "" || full == emitted {
			continue
		}
		delta := full
		if strings.HasPrefix(full, emitted) {
			delta = full[len(emitted):]
		}
		select {
		case out <- delta:
		case <-ctx.Done():
			return
		}
		emitted = full
	}
}

func cleanupSandbox(path string) {
	if err := os.RemoveAll(path); err != nil {
		log.Printf("ianua: sandbox cleanup %s: %v", path, err)
	}
}

func (c ClaudeBackend) Stream(ctx context.Context, req ChatRequest) (<-chan string, error) {
	system, prompt := collapseMessages(req.Messages)

	model := req.Model
	if model == "" || model == "claude" {
		model = "sonnet"
	}

	// claude inherits cwd-derived project state (CLAUDE.md, git repo,
	// hooks) from the caller, which can trigger interactive policy prompts
	// that block headless -p runs. Sandbox each invocation in a fresh
	// tempdir to keep the CLI environment-clean.
	sandbox, err := os.MkdirTemp("", "ianua-claude-")
	if err != nil {
		return nil, fmt.Errorf("claude sandbox dir: %w", err)
	}

	// args are passed as separate argv to exec.Command — not interpolated into
	// a shell. Caller-controlled model/prompt/system are inert here.
	// #nosec G204
	cmd := exec.CommandContext(ctx, "claude", claudeArgs(model, prompt, system, req.Effort())...)
	cmd.Dir = sandbox
	cmd.Stderr = io.Discard
	cmd.Stdin = strings.NewReader("")

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		cleanupSandbox(sandbox)
		return nil, fmt.Errorf("claude stdout pipe: %w", err)
	}

	if err := cmd.Start(); err != nil {
		cleanupSandbox(sandbox)
		return nil, fmt.Errorf("claude start: %w", err)
	}

	out := make(chan string, 16)
	go func() {
		defer close(out)
		defer cleanupSandbox(sandbox)
		defer func() {
			if err := cmd.Wait(); err != nil {
				// claude often exits non-zero on context cancel; debug only.
				log.Printf("ianua: claude exit: %v", err)
			}
		}()
		pumpStream(ctx, stdout, out)
	}()

	return out, nil
}
