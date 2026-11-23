# Limen

Limen packages the Muse Gadget SDK as a container. The container runs
one registered Linux gadget and one OpenAI-compatible shim in front of
it. OpenAI clients talk to the shim. The shim talks to the gadget
service. The gadget service talks to Muse.

## What Limen is

Limen is a bridge. It exposes Muse as a plain OpenAI-compatible API.
Any OpenAI client can use it. The shim accepts
`POST /v1/chat/completions` and `GET /v1/models`. It returns standard
`chat.completion` objects and OpenAI SSE chunks. The OpenAI Chat API
reference describes that surface:
<https://platform.openai.com/docs/api-reference/chat>.

Limen does not reimplement Muse. It wraps the upstream SDK
([facebookincubator/muse-gadget-sdk](https://github.com/facebookincubator/muse-gadget-sdk),
pinned in the Dockerfile) and adds two local patches: one raises the
chat timeout, one streams subscription events over the local socket.
The upstream SDK owns the protocol. The shim owns the HTTP surface.

## How it works

The request path has three hops.

1. The client calls the shim HTTP server.
2. The shim sends one JSON line to the gadget service over a Unix
   socket. The service sends the turn to Muse.
3. The service answers with one result line, or with event lines and
   one result line for a streaming turn. The shim translates the
   answer into an OpenAI response.

The shim flattens each request into one user message. It joins the
request messages as `role: text` lines. Conversation continuity lives
in the Muse session named by `session_id`. The shim keeps no
conversation state. The shim never logs message contents. It logs
lengths, timings, and event types only.

How you expose the shim (port mapping, reverse proxy, TLS) is your
choice. This document stops at the container. It does not cover
deployment.

## Configuration

### Image and ports

Pull the published image `ghcr.io/streambinder/limen`. The image is
built from the `Dockerfile` in this directory. It pins the upstream
SDK commit. It runs on `linux/arm64`.

The container mounts two volumes.

- The state directory maps to `/var/lib/musegadget` inside the
  container. It holds the pairing data and the SDK token.
- The workspace directory maps to `/workspace` inside the container.
  It holds the reply drop directory (`/workspace/replies`).

The shim listens on port 8001 inside the container. The image
exposes that port. Publish it in the way your setup needs.

The container runs as root. The gadget service drops privileges to
the unprivileged `gadget` account for each command it runs. The
container health check tests for the gadget socket.

### Environment variables

| Variable                | Default                           | Meaning                                                                             |
| ----------------------- | --------------------------------- | ----------------------------------------------------------------------------------- |
| `MUSEGADGET_SOCKET`     | `/run/musegadget/musegadget.sock` | Unix socket of the gadget service                                                   |
| `SHIM_PORT`             | `8001`                            | Port of the shim HTTP server                                                        |
| `SHIM_TIMEOUT_S`        | `1800`                            | Socket timeout for one turn                                                         |
| `SHIM_MODEL_ALIASES`    | (none)                            | Comma-separated extra Muse aliases for the same Muse; fallback when discovery fails |
| `SHIM_DISCOVERY_WAIT_S` | `60`                              | Seconds to wait for the service at startup while learning the Muse name             |
| `SHIM_REPLIES_DIR`      | `/workspace/replies`              | Reply drop directory                                                                |
| `SHIM_REPLY_WAIT_S`     | `600`                             | Seconds to wait for a reply                                                         |
| `SHIM_API_KEYS`         | (empty)                           | Comma-separated API keys                                                            |
| `MUSEGADGET_SDK_TOKEN`  | (none)                            | SDK token, written to the state directory at start                                  |
| `MUSEGADGET_STATE_DIR`  | `/var/lib/musegadget`             | State directory                                                                     |
| `MUSEGADGET_RUN_AS`     | `gadget`                          | Account that runs gadget commands                                                   |

With no `SHIM_API_KEYS` set, the shim is open. Use that mode on
trusted networks only. With keys set, every `/v1/*` request needs a
matching `Authorization: Bearer` header. A missing or wrong key gets
a 403 with `invalid_api_key`. `/healthz` stays open.

### Pairing

Pairing is a one-time step. It registers this container as a Linux
gadget with its own SDK token. The container entrypoint offers a
`pair` mode for this step. The SDK token is mandatory and has no
default. It arrives through the environment and the entrypoint stores
it in the state directory with mode 600. Pairing data stays in the
state volume across restarts. Re-pairing is not needed after a
redeploy.

For the official pairing guide, read the Linux SDK readme:
<https://github.com/facebookincubator/muse-gadget-sdk/blob/main/linux/README.md>.
Get an SDK token first. Every gadget needs one to pair.

### Client configuration

A client needs three values.

- `baseUrl`: the URL where you expose the shim, with the `/v1`
  path.
- `model`: a Muse address. See
  [Model addressing](#model-addressing).
- Session: a real Muse session UUID, sent as the `X-Session-Id`
  header. The shim also accepts `session_id` or `user` in the
  request body.

The session ID must be a real Muse session UUID. A non-UUID value
is rejected by the service. With no session source the turn goes to
the main chat.

## Capabilities

### Non-streaming completions

A non-streaming call uses the upstream wait path. The shim sends the
plain prompt with a `wait` field. The service waits for the finished
reply and returns its text in `reply`. The wait cap is 600 seconds.
The service also returns `partial` when the wait runs out mid-answer.
The shim accepts a partial reply as the delivered text and logs it.

When the wait yields no text, the shim falls back to the receipt
payload. The receipt carries a delivery confirmation, not the
assistant text. The shim extracts text from the receipt when it can.
A client opts out of the wait per request with
`"wait_reply": false`. The call then returns the receipt immediately.

### Streaming completions

A call with `stream: true` opens a subscription on the session. The
shim translates subscription events into OpenAI SSE chunks as they
arrive. A `delta.text_append` event becomes one chunk. A
`delta.message_done` event carries the full authoritative text. The
shim checks the full text against the accumulated deltas. SSE cannot
retract text, so on a mismatch the streamed text stands and the shim
logs the lengths only. Status events (`agent.status`,
`task.status`) are dropped by design. The client shows its own
working indicator.

Live deltas arrive only for turns in the primary session. See
[Limitations](#limitations). A streaming turn in a thread session
gets no live deltas. The shim then falls back to the reply drop:
it appends a note to the forwarded prompt that asks the agent to
write its complete reply, verbatim, to
`/workspace/replies/<correlation-id>.txt` on the gadget, and it
waits for that file. When the file never arrives, the shim falls
back to the receipt text.

In progress: the fallback is changing. The streaming path will send
the turn with the wait field in a worker thread while it drains the
subscription. When deltas arrive, they stream live. When no deltas
arrive, the wait text becomes the reply. The reply drop stays only
as a last resort. The goal is best-effort streaming with a
guaranteed final text. Fake streaming (a typewriter rendering of a
complete reply) is not used. Only real server tokens are streamed.

### Listen-only mode

A streaming call with `"listen_only": true` opens the subscription
without sending anything. It observes a turn that started
elsewhere. Each `message.user` event restarts the correlation. The
mode requires `stream: true`.

### Models and health

`GET /v1/models` lists the discovered Muse name first, then the configured aliases.
`GET /healthz` returns 200 when the gadget socket exists
and 503 when it does not. The health endpoint needs no key.

### Model addressing

The model in a completion request names a Muse and, optionally, a
conversation inside it. There is no default model: at startup the
shim learns the attached Muse's name from the gadget service and
serves it as its model. `SHIM_MODEL_ALIASES` adds further names for
the same Muse and is the fallback when discovery fails; with
neither the shim refuses to start.

Discovery asks the service for the Muse identity (`GET /identity`)
through the local socket. The service may not be registered yet
when the shim starts, so discovery retries for up to
`SHIM_DISCOVERY_WAIT_S` seconds.

A model value has one of these forms:

- `<alias>`: that Muse, main chat.
- `<alias>/main`: that Muse, main chat, spelled out.
- `<alias>/<uuid>`: that conversation inside that Muse.

`<uuid>` is a Muse session UUID. The part after the slash must be
`main` or a valid UUID. Any other value gets a 400.

The conversation in the model wins over the session source. The
session source is the `X-Session-Id` header, then the `session_id`
body field, then the `user` body field. With a bare model the session
source wins. With neither the turn goes to the main chat. A client
that sends no model gets a 400. A client that sends no
session source and a bare model lands on the main chat.

An unknown alias gets a 404 with code `model_not_found`.

## Authentication

Three credentials exist. Each one guards a different hop. No
credential value is ever printed or logged. Only token lengths and
identifiers appear in logs.

### The shim API key

OpenAI clients authenticate to the shim with a Bearer key. The key
comes from `SHIM_API_KEYS`. The shim compares it in constant time.
The key guards the shim. It has no relation to the Muse account.
Rotate it by changing the environment and restarting the container.

### The gadget channel

The gadget channel is the path the shim uses today. It has two
credentials.

- The SDK token. Pairing creates it. The entrypoint stores it in
  the state directory. The service uses it to authenticate as a
  registered gadget.
- The device token pair. Pairing stores it in `pairing.json` in the
  state directory. The access token lives about four hours. The
  service refreshes it automatically about every three hours. The
  refresh uses the stored refresh token.

The service fetches the list of virtual machines with the device
access token. The fetch returns one entry per VM with a `vm_id` and
a `vm_auth_token`. The token belongs to that VM only. The service
opens a WebSocket tunnel to the gateway host with the `vm_id` in
the query string. The tunnel runs Noise `Noise_XX_25519_AESGCM_SHA256`
with an ephemeral keypair. The service sends the `vm_auth_token` as
an `Authorization: Bearer` header at the upgrade. The tunnel then
carries the service frames for chat, subscribe, and file commands.

### The web channel

The web channel reuses the same `vm_auth_token` as the gateway
hatch token. It needs no browser and no cookies after pairing. The
tunnel is identical: same host, same path, same Noise handshake,
same frame format. Only the token presentation differs. The web
client sends the token as an `auth_token` query parameter. The
gadget SDK sends it as an `Authorization: Bearer` header. Both
forms are accepted by the gateway edge.

On the web channel, `chat.history` and `chat.stream` work with the
device credential. `sessions.list` and `session.start` do not. The
service layer refuses them with 403, "route not allowed for this
credential's scopes". A fresh session UUID works instead. The
gateway auto-creates the session on first use. The web channel is
not wired into the shim today. See
[Routing between the two clients](#routing-between-the-two-clients).

### Credential scopes

The shim authenticates with a gadget credential. The gadget
credential reaches the chat routes only: history, stream, subscribe,
and stream events. It does not reach session management routes:
session list, session get, chat search, session rename, session
archive, or turn cancel. The server refuses those routes with a 403
for this credential.

A user credential reaches the session management routes. The web
client uses a user credential, so it lists sessions by name. The shim
cannot list sessions by name. It resolves a name only from static
configuration.

Live deltas are not a scope difference. The server sends live deltas
only for main-chat turns, for both credentials.

## Routing between the two clients

Limen has two possible transports. They share one token.

- The gadget channel. The shim uses it today. It sends turns with
  `send_chat`, subscribes with `subscribe_chat`, and waits with the
  `wait` field. It speaks to the gadget service over the local Unix
  socket. The SDK owns this path. Upstream supports it by design.
- The web channel. It speaks the muse.ai gateway protocol directly
  over WebSocket and Noise. It is available as a second transport.
  It is not wired into the shim. It stays open for future use if a
  distinction is found that justifies it.

The evidence sets the routing rule. Live deltas are emitted only
for turns in the primary session. That rule holds on both channels.
A thread turn never streams, whether a human types it or an API
sends it. A thread turn always goes through the wait path. The
channel choice does not change streaming for thread sessions. The
web channel would only matter if it offered a capability the gadget
channel lacks. No such capability is known today.

## Limitations

- **Live deltas need the primary session.** The server emits
  `delta.*` events only for turns in the primary session. Thread
  turns never stream. The rule holds on both channels.
- **Upstream takes replies from the finished row by design.** The
  upstream SDK takes replies from the finished `message.assistant`
  row, so gadget-sent turns get their replies either way. Upstream
  issue
  [#330](https://github.com/facebookincubator/muse-gadget-sdk/issues/330)
  records the discussion. No live deltas are coming for
  gadget-initiated turns. The sanctioned route is the wait path.
- **API-injected turns are obeyed unreliably.** The receiving agent
  can tell that an injected turn does not come from the owner's
  device. A turn injected through the API may be refused. Do not
  rely on injected turns for unattended work.
- **Some gateway routes refuse device credentials.** `sessions.list`
  and `session.start` return 403 for the device credential. Use a
  fresh session UUID instead. The gateway creates the session on
  first use.
- **One wait per session at a time.** The service holds a
  per-session lock. A second concurrent wait on the same session is
  rejected. The shim falls back to the drop path in that case.
- **The wait caps at 600 seconds.** The service limit is 600
  seconds. The shim default matches it. A turn that runs longer
  returns a partial reply or no reply.
- **An idle streaming connection can be dropped.** A proxy or load
  balancer between the client and the shim can close an idle SSE
  connection. Real turns complete well before that. A long wait on
  a thread session can still hit the limit. The client then sees a
  dropped connection, not an error payload.
- **The reply drop is a fallback only.** It requires the agent to
  write a file on the gadget. It depends on the agent reading the
  note and obeying it. The hybrid streaming change replaces it
  with the wait path as the streaming fallback.
- **The web protocol is reverse-engineered.** The gateway protocol
  is undocumented. The web client reimplements it from the web
  bundle. It can break silently when the bundle changes.
  Tool and function calling are unmapped. Only text chat is
  covered.

## Verify it works

Run these checks after you start the container.

1. Check the container. The container list shows the `limen`
   container with a fresh creation time. The container log shows
   the "registered with the Muse" line with a fresh timestamp.
2. Check the health endpoint. `GET /healthz` on the shim port
   returns 200 with `"ok": true`. It returns 503 when the gadget
   socket is missing.
3. Check the models endpoint without a key. `GET /v1/models`
   without an `Authorization` header returns 403 with
   `invalid_api_key`.
4. Check the models endpoint with a key. `GET /v1/models` with a
   valid key returns one model entry.
5. Send one non-streaming turn on a fresh session. The reply
   arrives in seconds. The shim log shows a "wait reply after"
   line with the elapsed time. The log shows no drop fallback.
6. Send one streaming turn on a thread session. The reply arrives
   as one block at the end. The shim log records the stream completion
   with zero appends and the response length.

## Development

Tests live next to the code they cover. The suite covers the shim
and the subscribe patch. The coverage gate is 90 percent. Run the
suite from `ai/limen` with the SDK source tree set:

```sh
MUSEGADGET_SDK_SRC=<extracted SDK tree> uv run --with cryptography python -m pytest -q
```

Type checks run with `uvx mypy --strict`. Lint runs with
`ruff check`. The CI pipeline is the source of truth for formatting.
Local formatter output can reformat pre-existing lines. Fix only
your own lines, exactly as the CI diff shows.
