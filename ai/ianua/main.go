package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"strings"
	"time"
)

var backends = map[string]Backend{}

func registerBackend(b Backend) {
	for _, m := range b.Models() {
		backends[m] = b
	}
}

func pickBackend(model string) Backend {
	if b, ok := backends[model]; ok {
		return b
	}
	// also accept "claude:<variant>" style
	if i := strings.Index(model, ":"); i > 0 {
		if b, ok := backends[model[:i]]; ok {
			return b
		}
	}
	return nil
}

func handleModels(w http.ResponseWriter, _ *http.Request) {
	list := ModelList{Object: "list"}
	for id := range backends {
		list.Data = append(list.Data, Model{
			ID:      id,
			Object:  "model",
			Created: time.Now().Unix(),
			OwnedBy: "ianua",
		})
	}
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(list); err != nil {
		log.Printf("encode models: %v", err)
	}
}

func handleChat(w http.ResponseWriter, r *http.Request) {
	var req ChatRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "bad request: "+err.Error(), http.StatusBadRequest)
		return
	}

	b := pickBackend(req.Model)
	if b == nil {
		http.Error(w, "unknown model: "+req.Model, http.StatusNotFound)
		return
	}

	ctx, cancel := context.WithCancel(r.Context())
	defer cancel()

	deltas, err := b.Stream(ctx, req)
	if err != nil {
		http.Error(w, "backend start: "+err.Error(), http.StatusBadGateway)
		return
	}

	id := fmt.Sprintf("chatcmpl-%d", time.Now().UnixNano())
	created := time.Now().Unix()

	if req.Stream {
		writeSSE(w, id, created, req.Model, deltas)
		return
	}
	writeJSON(w, id, created, req.Model, deltas)
}

func writeSSE(w http.ResponseWriter, id string, created int64, model string, deltas <-chan string) {
	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming unsupported", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")

	send := func(chunk ChatChunk) error {
		buf, err := json.Marshal(chunk)
		if err != nil {
			return err
		}
		if _, err := fmt.Fprintf(w, "data: %s\n\n", buf); err != nil {
			return err
		}
		flusher.Flush()
		return nil
	}

	// initial role chunk (OpenAI convention)
	if err := send(ChatChunk{
		ID: id, Object: objectChunk, Created: created, Model: model,
		Choices: []DeltaChoice{{Delta: ChatMessage{Role: roleAssistant}}},
	}); err != nil {
		return
	}

	for d := range deltas {
		if err := send(ChatChunk{
			ID: id, Object: objectChunk, Created: created, Model: model,
			Choices: []DeltaChoice{{Delta: ChatMessage{Content: d}}},
		}); err != nil {
			return
		}
	}

	stop := "stop"
	if err := send(ChatChunk{
		ID: id, Object: objectChunk, Created: created, Model: model,
		Choices: []DeltaChoice{{FinishReason: &stop}},
	}); err != nil {
		return
	}
	if _, err := fmt.Fprint(w, "data: [DONE]\n\n"); err != nil {
		return
	}
	flusher.Flush()
}

func writeJSON(w http.ResponseWriter, id string, created int64, model string, deltas <-chan string) {
	var full strings.Builder
	for d := range deltas {
		full.WriteString(d)
	}
	resp := ChatResponse{
		ID: id, Object: "chat.completion", Created: created, Model: model,
		Choices: []Choice{{
			Index:        0,
			Message:      ChatMessage{Role: roleAssistant, Content: full.String()},
			FinishReason: "stop",
		}},
		Usage: Usage{},
	}
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(resp); err != nil {
		log.Printf("encode response: %v", err)
	}
}

func main() {
	port := flag.Int("port", 8080, "listen port")
	claudeExtra := flag.String("claude-extra-args", "", "extra args prepended to every claude invocation (whitespace-split, no quoting)")
	flag.Parse()

	registerBackend(ClaudeBackend{ExtraArgs: strings.Fields(*claudeExtra)})

	mux := http.NewServeMux()
	mux.HandleFunc("GET /v1/models", handleModels)
	mux.HandleFunc("POST /v1/chat/completions", handleChat)

	addr := fmt.Sprintf(":%d", *port)
	log.Printf("ianua listening on %s — backends: %d models", addr, len(backends))
	srv := &http.Server{
		Addr:              addr,
		Handler:           mux,
		ReadHeaderTimeout: 10 * time.Second,
	}
	log.Fatal(srv.ListenAndServe())
}
