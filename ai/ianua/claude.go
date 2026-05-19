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
	"regexp"
	"strings"
)

type ClaudeBackend struct {
	// ExtraArgs are prepended to every claude invocation. Configured via the
	// -claude-extra-args CLI flag so users can mirror their shell alias (e.g.
	// `--dangerously-skip-permissions`) without ianua having to source rc files.
	ExtraArgs []string
}

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

func claudeArgs(model, prompt, system, effort string, extra []string) []string {
	args := append([]string{}, extra...)
	args = append(
		args,
		"-p", strings.TrimSpace(prompt),
		"--model", model,
		"--output-format", "stream-json",
		"--verbose",
		"--no-session-persistence",
	)
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

// forge (and other agentic clients) embed the caller's working directory in
// the system prompt so the model can resolve relative paths. Honour that hint
// when present so claude's file tools see the same cwd the user is in.
var cwdHintRE = regexp.MustCompile(`<current_working_directory>\s*(.+?)\s*</current_working_directory>`)

func extractCwd(messages []ChatMessage) string {
	for _, m := range messages {
		match := cwdHintRE.FindStringSubmatch(m.Content)
		if len(match) < 2 {
			continue
		}
		candidate := strings.TrimSpace(match[1])
		info, err := os.Stat(candidate)
		if err != nil || !info.IsDir() {
			continue
		}
		return candidate
	}
	return ""
}

func (c ClaudeBackend) Stream(ctx context.Context, req ChatRequest) (<-chan string, error) {
	system, prompt := collapseMessages(req.Messages)

	model := req.Model
	if model == "" || model == "claude" {
		model = "sonnet"
	}

	// Prefer the caller's actual working dir (extracted from the system prompt
	// hint forge and friends inject) so file tools resolve relative paths the
	// way the user expects. When no hint is present, sandbox the invocation in
	// a fresh tempdir to keep CLAUDE.md auto-discovery / hooks from triggering
	// interactive policy prompts that would block headless -p runs.
	workDir := extractCwd(req.Messages)
	var sandbox string
	if workDir == "" {
		s, err := os.MkdirTemp("", "ianua-claude-")
		if err != nil {
			return nil, fmt.Errorf("claude sandbox dir: %w", err)
		}
		sandbox = s
		workDir = s
	}

	// args are passed as separate argv to exec.Command — not interpolated into
	// a shell. Caller-controlled model/prompt/system are inert here.
	// #nosec G204
	cmd := exec.CommandContext(ctx, "claude", claudeArgs(model, prompt, system, req.Effort(), c.ExtraArgs)...)
	cmd.Dir = workDir
	cmd.Stderr = io.Discard
	cmd.Stdin = strings.NewReader("")

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		if sandbox != "" {
			cleanupSandbox(sandbox)
		}
		return nil, fmt.Errorf("claude stdout pipe: %w", err)
	}

	if err := cmd.Start(); err != nil {
		if sandbox != "" {
			cleanupSandbox(sandbox)
		}
		return nil, fmt.Errorf("claude start: %w", err)
	}

	out := make(chan string, 16)
	go func() {
		defer close(out)
		if sandbox != "" {
			defer cleanupSandbox(sandbox)
		}
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
