# Ianua

OpenAI-compatible HTTP shim that forwards chat completions to local AI
CLIs (claude, codex, gemini, opencode).

## How to use

Run the server:

```bash
go run . -port 8080
```

Point any OpenAI-compatible client at `http://localhost:8080/v1`:

```bash
curl http://localhost:8080/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{
        "model": "sonnet",
        "messages": [{"role": "user", "content": "say hi"}],
        "stream": true
    }'
```

## Backends

Currently only `claude` is wired. Exposed models: `claude`, `sonnet`, `opus`, `haiku`.
