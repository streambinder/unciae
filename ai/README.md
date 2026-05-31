# Canon — Repository Guidelines

Universal guidelines for repositories under this meta-repository. Stack-agnostic, tooling-agnostic where possible. Intended as durable reference for **any** AI assistant, code generator, contributor, or future-self consulting standards.

These are **suggestions**, not enforced rules. Surface drift; propose alignment; let owner decide.

---

## 1. Repository Topology

Each top-level directory in the meta-repository is an independent Git repository. Each repository has its own `.git`, history, remote, CI. Treat repository boundary as hard — no cross-repository automation without explicit intent.

A per-repository `CLAUDE.md` / `AGENTS.md` / equivalent overrides these guidelines for that repository.

---

## 2. Repository Root Hygiene

**Root path stays minimal.** Move anything that can live in a subdirectory out of root.

- `Readme.md` → `.github/README.md` (GitHub still renders it from `.github/` for repository landing page).
- `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, issue/PR templates → `.github/`.
- Tooling configs → dedicated dirs where the tool allows (`.config/`, `tools/`, language-native locations).
- Acceptable at root only: `LICENSE`, `.gitignore`, language manifest (`go.mod`, `package.json`, `pyproject.toml`, `pubspec.yaml`), `.editorconfig`, `.github/`.
- Sprawling root (>~8 visible entries) → propose move.

---

## 3. Linting — super-linter

[`super-linter`](https://github.com/super-linter/super-linter) is the **de-facto linter for all repositories**. Run via GitHub Actions.

- Use **defaults** wherever possible. Override only with strong justification, documented in workflow comment.
- Invoked as job inside `.github/workflows/push.yml` (see §11), not separate `lint.yml`.
- Per-language linter configs (`.eslintrc`, `.golangci.yml`, etc.) only when defaults genuinely don't fit.
- `super-linter` covers secret scanning — no separate `gitleaks`/`trufflehog` workflow.
- Avoid bespoke per-language lint workflows — consolidate under super-linter.

### 3.1 Canonical Formatters (match super-linter locally)

Format/autofix with the **same tool super-linter ships** before linting, committing, or running tests. Avoids CI ↔ local drift. All super-linter `FIX_*` envs default `false`; treat the table below as the local equivalent to opt-in fix mode.

| Language                            | Tool                                    | Local command                         | super-linter `FIX_*`                                                                |
| ----------------------------------- | --------------------------------------- | ------------------------------------- | ----------------------------------------------------------------------------------- |
| Go                                  | `gofumpt` (preferred), else `gofmt`     | `gofumpt -w .`                        | `FIX_GO`, `FIX_GO_MODULES`                                                          |
| Python                              | `ruff format` + `isort` (or `black`)    | `ruff format . && ruff check --fix .` | `FIX_PYTHON_RUFF_FORMAT`, `FIX_PYTHON_RUFF`, `FIX_PYTHON_ISORT`, `FIX_PYTHON_BLACK` |
| JavaScript / TS                     | `prettier` + `eslint --fix`             | `prettier -w . && eslint --fix .`     | `FIX_{JAVASCRIPT,TYPESCRIPT}_{PRETTIER,ES}`, `FIX_BIOME_FORMAT`                     |
| JSON / YAML / Markdown / CSS / HTML | `prettier`                              | `prettier -w .`                       | `FIX_{JSON,YAML,MARKDOWN,CSS,HTML}_PRETTIER`                                        |
| Shell / Bash                        | `shfmt`                                 | `shfmt -w .`                          | `FIX_SHELL_SHFMT`                                                                   |
| Rust                                | `rustfmt` + `clippy --fix`              | `cargo fmt && cargo clippy --fix`     | `FIX_RUST_<edition>`, `FIX_RUST_CLIPPY`                                             |
| Dart / Flutter                      | `dart format` (super-linter lints only) | `dart format .`                       | — (no fix mode in super-linter; run locally)                                        |
| Terraform                           | `terraform fmt`                         | `terraform fmt -recursive`            | `FIX_TERRAFORM_FMT`                                                                 |
| Dockerfile                          | none (lint via `hadolint`)              | `hadolint Dockerfile`                 | —                                                                                   |

Rules:

- **Before commit / before push**: run the formatter for every language touched. Keeps super-linter green on first CI pass.
- **Before tests**: format first — formatter-induced diffs caught at lint stage waste a CI cycle.
- One canonical formatter per language per repository. Don't mix `black` and `ruff format`, or `prettier` and `biome`, in the same repository.
- If a repository pins a different choice (per-repository `CLAUDE.md` / config), respect it — flag the divergence, don't auto-switch.

### 3.2 super-linter Performance Tuning

GitHub Actions minutes are the binding constraint. super-linter is the single biggest job on most repositories — tune for speed by default.

- **Variant**: `super-linter/super-linter/slim@<sha>` (drops .NET / Ansible / Java images). The full image triples pull time without adding linters used here. No "slimmer" official variant exists — a hand-rolled image is not worth the maintenance.
- **Required env knobs** (set in every super-linter step):
  - `SAVE_SUPER_LINTER_OUTPUT: false` — skip writing per-linter logs to disk; default `true` wastes I/O on every run.
  - `MULTI_STATUS: false` — collapse N per-linter PR statuses into one. Cuts GitHub API calls (each status is a network round-trip) and keeps the PR checks panel tidy.
  - `LOG_LEVEL: WARN` — default `INFO` is chatty; lowers log volume and write overhead.
- **`VALIDATE_*` disables** — only when another job in the same `push.yml` already covers that language surface (e.g. dedicated `gofumpt`/`mypy` jobs). Every disable carries a comment naming the job that replaces it.
- **`fetch-depth: 0`** on the checkout step is required only when `VALIDATE_ALL_CODEBASE: true` (full-history scan). Keep it for master-push runs; PR runs use diff mode and don't need full history.
- **`VALIDATE_ALL_CODEBASE`** — `true` on push to `master`, `false` on `pull_request` (the existing `!contains(github.event_name, 'pull_request')` expression is the canonical form). Don't flip — full scans are the intended safety net post-merge.

### 3.3 Linter / Formatter Config Location

**All super-linter-consumed config files live under `.github/linters/`.** Single dedicated dir keeps repository root clean (§2) and groups CI tooling.

- Native super-linter location — picked up automatically (`LINTER_RULES_PATH` defaults to `.github/linters`). Examples: `.golangci.yml`, `.eslintrc*`, `.markdown-lint.yml`, `.python-lint`, `.ruff.toml`, `biome.json`, `.codespellrc`, `trivy.yaml`, `.mypy.ini`.
- **Tools that demand config at repository root** (refuse to discover under `.github/linters/`): keep canonical file in `.github/linters/`, **symlink it from root**. Single source of truth, root stays advisory only.
  - Common offenders: `commitlint` (`commitlint.config.js`), `biome` (`biome.json` when invoked as standalone CLI), some IDE-driven tools.
  - Symlink pattern: `ln -sf .github/linters/commitlint.config.js commitlint.config.js`.
  - Alternative when symlinks clash with platform / CI: workflow-level `mv` step (existing pattern — `mv -vf .github/linters/biome.json .github/linters/commitlint.config.js ./`). Symlink preferred — survives outside CI; `mv` only when symlinks confuse the tool.
- **Never** scatter linter configs across repository root or per-language subdirs when super-linter consumes them. One discovery path; if a tool can't be persuaded to look there, symlink — don't duplicate.
- Per-repository overrides allowed; document why in workflow comment per §3.

---

## 4. CI — paths-filter for Selective Jobs

Use [`dorny/paths-filter`](https://github.com/dorny/paths-filter) action to gate jobs on changed files. Apply to **every repository with multiple logical components** (backend/frontend, multiple services, documentation versus source, etc.).

Pattern:

```yaml
jobs:
  changes:
    runs-on: ubuntu-latest
    outputs:
      backend: ${{ steps.filter.outputs.backend }}
      frontend: ${{ steps.filter.outputs.frontend }}
    steps:
      - uses: actions/checkout@v4
      - uses: dorny/paths-filter@v3
        id: filter
        with:
          filters: |
            backend:
              - 'backend/**'
            frontend:
              - 'app/**'

  backend-test:
    needs: changes
    if: needs.changes.outputs.backend == 'true'
    # ...

  frontend-test:
    needs: changes
    if: needs.changes.outputs.frontend == 'true'
    # ...
```

Rules:

- One `changes` job, multiple filter outputs — one per logical component matching directory layout.
- Downstream jobs `needs: changes` + `if: needs.changes.outputs.<name> == 'true'`.
- Filter globs mirror repository's actual top-level component dirs.
- Saves CI minutes, faster feedback.

---

## 5. Workflow Hygiene — No Static Constants

**Never hardcode tags, versions, image names, or repeated strings in workflows.** Use template variables.

Rule: if a value is **already exposed** via GitHub context (`github.*`, `runner.*`, `secrets.*`, etc.), use the context expression **directly** — do not re-alias it through `env`. Only define `env` for values that have no upstream source (tool versions, custom config strings).

Bad — hardcoded:

```yaml
- uses: actions/setup-go@v5
  with:
    go-version: "1.23"
- run: docker build -t myorg/myapp:1.2.3 .
```

Bad — pointless re-alias of exposed context:

```yaml
env:
  IMAGE_NAME: ${{ github.repository }}
  IMAGE_TAG: ${{ github.sha }}
jobs:
  build:
    steps:
      - run: docker build -t ${{ env.IMAGE_NAME }}:${{ env.IMAGE_TAG }} .
```

Good — `env` only for values with no upstream source, context used directly otherwise:

```yaml
env:
  GO_VERSION: "1.23"
jobs:
  build:
    steps:
      - uses: actions/setup-go@v5
        with:
          go-version: ${{ env.GO_VERSION }}
      - run: docker build -t ${{ github.repository }}:${{ github.sha }} .
```

- Pin action versions by SHA where possible.
- Reuse via `workflow_call` / composite actions when same logic repeats across repositories.

### 5.1 Docker Image Names — Derive From `github` Context

Docker image references in workflows (build tags, push targets, `images:` inputs to `docker/metadata-action`, etc.) **must derive owner and repository from `${{ github.repository }}`** (or `${{ github.repository_owner }}` when only the owner is needed). Never hardcode `owner/repository` literals.

Default registry: **GHCR** (`ghcr.io`). Other registries fine when justified — same rule applies (no hardcoded owner/repository segment).

Bad — hardcoded owner/repository:

```yaml
- run: docker build -t ghcr.io/myorg/myapp:${{ github.sha }} .
- uses: docker/metadata-action@v5
  with:
    images: ghcr.io/myorg/myapp
```

Good — derived from context:

```yaml
- run: docker build -t ghcr.io/${{ github.repository }}:${{ github.sha }} .
- uses: docker/metadata-action@v5
  with:
    images: ghcr.io/${{ github.repository }}
```

Rules:

- Repository rename / fork / transfer keeps workflows working without edit.
- Lowercase requirement of GHCR: `${{ github.repository }}` already lowercase for standard repos; if owner contains uppercase, pipe through `tr '[:upper:]' '[:lower:]'` in a prior step rather than hardcoding.
- Multi-image repositories (one workflow builds N images): suffix off `${{ github.repository }}` — e.g. `ghcr.io/${{ github.repository }}/backend`, `ghcr.io/${{ github.repository }}/app`. Image name segment after the repository path is fine to literal-string, the owner/repository segment is not.
- Per-repository override allowed when a repository intentionally publishes under a different namespace (e.g. org-wide shared image name). Document the override in workflow comment per §3.

### 5.2 Docker Tag Pairing — `:latest` Plus Commit SHA

**Every Docker push publishes at least two tags pointing at same digest: `:latest` and the commit SHA (`${{ github.sha }}`).** Mutable pointer for "current tip", immutable pointer for exact provenance. Consumers pin SHA in prod, track `:latest` for dev.

Bad — single floating tag, no immutable pointer:

```yaml
- uses: docker/build-push-action@v6
  with:
    push: true
    tags: ghcr.io/${{ github.repository }}:latest
```

Bad — single SHA, no convenience tag:

```yaml
- uses: docker/build-push-action@v6
  with:
    push: true
    tags: ghcr.io/${{ github.repository }}:${{ github.sha }}
```

Good — both tags, same digest (single push, multiple `tags:` entries):

```yaml
- uses: docker/build-push-action@v6
  with:
    push: true
    tags: |
      ghcr.io/${{ github.repository }}:latest
      ghcr.io/${{ github.repository }}:${{ github.sha }}
```

Good — `docker/metadata-action` generating both:

```yaml
- uses: docker/metadata-action@v5
  id: meta
  with:
    images: ghcr.io/${{ github.repository }}
    tags: |
      type=raw,value=latest
      type=sha,format=long
- uses: docker/build-push-action@v6
  with:
    push: true
    tags: ${{ steps.meta.outputs.tags }}
```

Rules:

- Use `${{ github.sha }}` (full 40-char SHA) — not short SHA. Unambiguous, matches `git log` / `gh` output exactly.
- On tag releases (`tag.yml`): mirror the pattern with `:release` as mutable pointer
  and `${{ github.ref_name }}` as immutable version tag (e.g. `v1.2.3`), plus
  `${{ github.sha }}` for exact provenance. Three tags minimum, same digest:
  `:release`, `:${{ github.ref_name }}`, `:${{ github.sha }}`. Do **not** push
  `:latest` from `tag.yml` — `:latest` belongs to master tip, `:release` belongs to
  most recent tagged release. Use `docker/metadata-action` with `type=semver` for
  richer fan-out (`v1.2.3`, `v1.2`, `v1`) alongside `type=raw,value=release`.
- Single `build-push-action` invocation pushing all tags — do not run multiple builds. Same digest must back every tag, otherwise SHA tag breaks reproducibility.
- `:latest` published only from `master` (`push.yml`). Feature branches: skip `:latest`, push branch-name tag (`type=ref,event=branch`) plus SHA. Tag releases (`tag.yml`) use `:release` instead — see rule above.
- Combine with §11.1: tag pairing applies inside push-gated job — never on PR events.

### 5.3 Docker Base Images — Alpine, Streamlined

**Prefer Alpine base images wherever possible.** `alpine:<version>`, `python:<ver>-alpine`, `node:<ver>-alpine`, `golang:<ver>-alpine`, etc. Smaller images, smaller attack surface, faster pulls.

Bad — full Debian/Ubuntu base when Alpine works:

```dockerfile
FROM python:3.13
FROM node:22
FROM golang:1.23 AS build
```

Good — Alpine variant:

```dockerfile
FROM python:3.13-alpine
FROM node:22-alpine
FROM golang:1.23-alpine AS build
```

Streamline rules — every Dockerfile should:

- **Multi-stage build** when producing a binary or compiled artifact. Build stage on toolchain image, final stage on minimal runtime (`alpine:<version>` or `scratch` for static binaries). Never ship the toolchain.
- **Single `RUN` chain for installs** with cleanup in same layer: `apk add --no-cache <pkgs>`. Never leave package cache, build deps, or temp files in final image.
- **`--no-cache` on `apk`**, `--no-install-recommends` if Debian-based exception applies, `pip install --no-cache-dir`, `npm ci --omit=dev`.
- **Drop build-only deps** before final stage. Use `apk add --virtual .build-deps <...>` then `apk del .build-deps` in same layer when build deps cannot be staged.
- **Pin base image tag** — exact version, not floating `:latest` or major-only. SHA-pin (`alpine:3.20@sha256:...`) where reproducibility matters.
- **Non-root user** in final stage (`adduser -D -H app && USER app`).
- **`.dockerignore`** present and tight — exclude `.git/`, tests, dev configs, lockfile-ignored artifacts.

When Alpine is **not** viable, document why in `Dockerfile` comment and pick the smallest alternative — `-slim` Debian variants, `distroless`, or `scratch`. Common Alpine blockers: glibc-only binaries (use `gcompat` or pick `-slim`), CUDA/GPU runtimes, vendor-supplied images without Alpine variant, Python wheels without musl builds (build from sdist or use `-slim`).

### 5.4 Docker Build Target — `linux/arm64` Only on Native Runner

**All Docker images target `linux/arm64` exclusively.** All deploy hosts under this meta-repository are arm64 (Raspberry Pi, arm servers); amd64 / armv7 builds waste CI minutes on artifacts no consumer pulls.

- **`platforms: linux/arm64`** — single value, bare `arm64` (not `arm64/v8`, not multi-arch CSV).
- **`runs-on: ubuntu-24.04-arm`** — native arm64 GitHub-hosted runner. Free for public repositories. Avoids QEMU entirely.
- **Forbidden**: `docker/setup-qemu-action`. QEMU on x86 runner is 5–10× slower than native arm64 and burns budget for zero benefit when only arm64 is shipped.
- **Multi-arch exception** (rare): if a specific image genuinely needs amd64 (e.g. one-off dev tooling), split into two jobs — `runs-on: ubuntu-latest` for amd64, `runs-on: ubuntu-24.04-arm` for arm64 — and merge via `docker/build-push-action` `outputs: type=image,push-by-digest=true` + `docker buildx imagetools create` manifest step. Never resort to QEMU.

Bad — QEMU + multi-arch fan-out on x86:

```yaml
runs-on: ubuntu-latest
steps:
  - uses: docker/setup-qemu-action@<sha>
  - uses: docker/setup-buildx-action@<sha>
  - uses: docker/build-push-action@<sha>
    with:
      platforms: linux/amd64,linux/arm/v7,linux/arm64/v8
```

Good — native arm64, single platform:

```yaml
runs-on: ubuntu-24.04-arm
steps:
  - uses: docker/setup-buildx-action@<sha>
  - uses: docker/build-push-action@<sha>
    with:
      platforms: linux/arm64
```

### 5.5 Docker Build Cache — GitHub Actions Cache Mandatory

**Every `docker/build-push-action` invocation MUST set `cache-from` and `cache-to` against the GitHub Actions cache backend.** Without it, every push re-downloads `go mod` / `apk add` / `pip install` layers from scratch. 40–70% reduction on incremental builds.

```yaml
- uses: docker/build-push-action@<sha>
  with:
    platforms: linux/arm64
    cache-from: type=gha
    cache-to: type=gha,mode=max
    tags: |
      ghcr.io/${{ github.repository }}:latest
      ghcr.io/${{ github.repository }}:${{ github.sha }}
    push: ${{ github.event_name != 'pull_request' }}
```

- **`mode=max`** caches every intermediate stage, not just the final image. Multi-stage Dockerfiles (the default per §5.3) need this — `mode=min` only caches the final stage.
- **`type=gha`** uses the same cache backend as `actions/cache`. Scoped per branch; falls back to base branch automatically.
- **Scope collision** (multi-image repos like `vigor`): set `cache-from: type=gha,scope=<image-name>` + `cache-to: type=gha,scope=<image-name>,mode=max` per build to avoid one image evicting another's cache.
- Pair with §5.4 — `ubuntu-24.04-arm` runner + GHA cache is the canonical build job shape.

---

## 6. Dependabot

**Required for every repository.** `.github/dependabot.yml` covering **all supported package ecosystems** present in the repository.

Detect ecosystems from manifests. Common entries:

- `github-actions` → `.github/workflows/`
- `gomod` → `go.mod` location
- `npm` → `package.json` location
- `pip` / `uv` → `pyproject.toml` / `requirements.txt` location
- `pub` → `pubspec.yaml` location
- `docker` → `Dockerfile` location

Defaults: weekly schedule, grouped minor/patch updates per ecosystem to reduce PR noise.

---

## 7. Commits & PRs

- **Conventional Commits everywhere**: `type(scope): subject`. Types: `feat|fix|refactor|chore|docs|test|ci|perf|build`.
- Subject ≤72 chars, imperative mood, no trailing period.
- **Subject = single plain phrase.** No punctuation other than the leading `type(scope):` separator. No parentheses, brackets, quotes, backticks, slashes, commas, semicolons, colons, em-dashes, or symbols inside the subject. No lists, no "X and Y / Z" enumerations — split into separate commits or use the body. Plain prose only.
  - Bad: `fix(api): handle (nil) responses, retry on 5xx`
  - Bad: `docs(ai): §3.2 added + §7/§20 updates`
  - Good: `fix(api): handle nil responses on retry`
  - Good: `docs(ai): consolidate linter configs under github linters`
- **Body: very very concise.** One short paragraph max. Skip body if subject is self-explanatory. Skip "what" — diff shows it. Only "why" if non-obvious.
- **Body = single grammatical sentence ending in one period.** Plain prose, no commas, semicolons, colons, em-dashes, parentheses, brackets, quotes, backticks, slashes, or list markers. No enumerations — split into separate commits if the change cannot be described as one sentence. Same symbol ban as the subject (§7), applied to the body.
  - Bad: `Switch to mono font, drop icons, rework footer.`
  - Bad: `Rework layout: unified wrap width and hairline rules.`
  - Good: `Switch to a single monospace identity across the site.`
- **Body line length ≤100 chars.** Matches `commitlint` `body-max-line-length` default. Hard-wrap longer lines. Includes URLs — break or shorten.
- One logical change per commit. No "misc fixes".
- PR title = top commit subject.
- Per-repository `commitlint` config aligned with above (suggest adding if missing).
- **CI-failure fixups: amend, never new commit.** When a pushed commit's CI fails (lint, format, test, build), fix locally, `git commit --amend` (re-sign), `git push --force-with-lease`. Applies on every branch including `master`. Keeps history bisect-clean — no "fix lint" / "fix CI" trailing commits. Use `--force-with-lease` (not `--force`) to abort if remote moved.

---

## 8. Language Code Layout

Respect language-idiomatic layout. **Do not force uniform `src/` across all stacks.**

| Lang             | Layout                                                                                                                                                                                                                                                                              |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Go               | [Standard Go Project Layout](https://github.com/golang-standards/project-layout): `cmd/`, `internal/`, `pkg/`, flat packages — no `src/`                                                                                                                                            |
| TS/JS (lib)      | `src/` + `dist/`, ESM, `package.json` `exports` field                                                                                                                                                                                                                               |
| TS/JS (Node app) | `src/`, `tests/`, build to `dist/`                                                                                                                                                                                                                                                  |
| Python           | [src-layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/): `src/<pkg>/`, `tests/`, `pyproject.toml`. Exception: single-file tool runners (e.g. `unciae/<category>/<tool>/main.py`) use flat layout — `main.py` + `pyproject.toml` adjacent (§21). |
| Dart/Flutter     | `lib/`, `test/`, `assets/`, idiomatic Flutter structure                                                                                                                                                                                                                             |
| Rust             | Cargo conventions: `src/`, `tests/`, `examples/`                                                                                                                                                                                                                                    |

Tests live alongside or in idiomatic test directory per lang — pick one per repository, stay consistent.

---

## 9. Language Conventions

- **Go**: `gofumpt`-clean, `any` over `interface{}`, errors wrapped with `%w`, table-driven tests.
- **TS**: strict mode, no `any` without comment, ESM, no default exports for libs.
- **Python**: see §21 — `uv` + `pyproject.toml` only, full type annotations, `ruff` + `mypy --strict`, `uv.lock` committed.
- **Dart**: null-safety, `const` constructors, `flutter_lints` baseline.

---

## 10. Branching & Releases

- **Primary branch**: `master`. Never assume `main`.
- **Feature branches**: `feat/<short-name>`. Catch-all prefix — covers fixes, chores, docs too unless context strongly justifies different prefix.
- **Signed commits**: **always**. Every commit GPG/SSH-signed.
- **Pull with rebase**: set `pull.rebase = true` globally. Reconciles divergent branches by replaying local commits on top of upstream instead of creating merge commits — keeps history linear and bisect-clean (§7) and avoids the `fatal: Need to specify how to reconcile divergent branches` prompt. Lives in the tracked `clavis/.gitconfig` dotfile so it deploys to every machine.
- **Tags**: `vMAJOR.MINOR.PATCH` (SemVer). No `v0` perpetual.
- **Release flow**: tag creation triggers `tag.yml` → release artifact published. CI on `master` push / PRs runs via `push.yml`.
- **No CHANGELOG file.** GitHub release notes auto-generated from commit history (Conventional Commits make this clean).

---

## 11. CI Workflow Naming

Two **canonical** workflows carry standard lint/build/test/deploy. Other narrow-purpose workflows fine when they serve a distinct concern.

- **`.github/workflows/push.yml`** — triggers on push to `master` and on pull requests. Houses standard CI: super-linter, build, test, coverage. Use `paths-filter` (§4) to gate per-component jobs.
- **`.github/workflows/tag.yml`** — triggers on tag creation matching `v*`. Houses release jobs: build artifacts, publish images/packages, create GitHub release.

Rules:

- **No** `lint.yml` / `ci.yml` / `test.yml` / `release.yml` — those collapse into `push.yml` or `tag.yml`.
- Other workflows allowed when single-purpose and orthogonal: `dependabot-auto-merge.yml`, `codeql.yml`, scheduled scans, `workflow_dispatch`-only ops, etc.
- Reusable logic via `workflow_call` / composite actions (§5), not duplicate top-level workflows.

### 11.1 Artifact Publishing — Never on Pull Requests

**Publishing steps must never run on `pull_request` events.** PR runs validate (lint, build, test); they do not push artifacts, images, packages, or releases. Forks can open PRs from untrusted code — running publish steps would leak credentials and pollute registries with unreviewed artifacts.

Publishing covers, non-exhaustive:

- `docker push` / registry login + push (GHCR, Docker Hub, ECR, GAR, etc.)
- `npm publish`, `cargo publish`, `pip` / `twine upload`, `pub publish`, `gem push`, `mvn deploy`
- `gh release create` / `softprops/action-gh-release` / equivalent
- `git push` of tags, generated artifacts, or pages branches
- `terraform apply`, `kubectl apply`, deployment hooks, webhook notifications to prod systems
- Uploading binaries to S3/GCS/object storage outside ephemeral cache scope

Rules:

- Gate every publish job/step with an event check. Examples (any equivalent works):
  - Job-level: `if: github.event_name != 'pull_request'`
  - On `tag.yml`: trigger only `on: push: tags: ['v*']` — no `pull_request`.
  - On `push.yml`: gate publish job with `if: github.event_name == 'push' && github.ref == 'refs/heads/master'`.
- Build/test steps stay unconditional (PRs must validate the same artifact path that ships).
- Never use `pull_request_target` to bypass this — that runs with write tokens against untrusted PR code (the exact failure mode this rule prevents).
- Secrets needed for publishing (`secrets.REGISTRY_TOKEN`, etc.) must never be referenced inside steps reachable from a `pull_request` trigger.
- Dry-run / build-only validation on PRs is encouraged: build the image, don't push; pack the package, don't publish.

### 11.2 Concurrency Control — Cancel In-Progress on All Refs

**Every `push.yml` MUST declare a top-level `concurrency:` block that cancels in-progress runs on every ref, including `master`.** Multiple rapid pushes otherwise spawn N parallel runs that race to publish the same artifact — wasted minutes and a non-deterministic "winner" at the registry.

```yaml
name: push

on:
  push: null
  pull_request: null

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

- **Group by `workflow + ref`** — independent branches do not block each other; rapid pushes to the same ref collapse to the latest.
- **`cancel-in-progress: true` on all refs (master included).** Rationale: with `VALIDATE_ALL_CODEBASE: true` on master, every run scans the full tree; the latest commit's run is strictly newer and supersedes the previous. The previous run's artifact would be overwritten anyway — cancel early, save the minutes.
- **`tag.yml`** uses a different group expression (`${{ github.workflow }}-${{ github.ref_name }}`) and `cancel-in-progress: false` — releases must complete, never be cancelled mid-publish.
- Other narrow-purpose workflows (`workflow_dispatch`, scheduled scans): add `concurrency:` when concurrent runs would conflict (shared external resource); skip when independent.

---

## 12. Readme Convention

Repositories use a **minimal readme**. Detailed docs live elsewhere (external site, `docs/`, or upstream project).

Canonical template (root or `.github/`):

```markdown
# <RepoName> <a href="<docs-url-or-repo-url>"><img alt="documentation" align="left" src="<owner-avatar-url>"></a>

<one-line description>
```

- Title-case repository name (Unicode OK).
- Anchor logo image links to docs site if exists, else upstream/repository URL.
- Body = single line. No install/usage/badges sections — those belong on docs site.
- If `docs/` folder exists (local or hosted), body = `Documentation available at [<host>](<url>).` pointing to hosted version.
- Otherwise body = **project one-liner from `pyproject.toml` description field, `go.mod` module comment, `package.json` description, or `pubspec.yaml` description**. Never use placeholder text like "Documentation not available yet" — implies imminent docs that may never appear.

---

## 13. Pre-commit Hooks

**No local pre-commit framework.** Rely on CI (`super-linter` via `push.yml`) as single source of truth for lint/format enforcement. Don't suggest `pre-commit`/`husky`/`lefthook` setups.

---

## 14. Coverage & Testing

- **Target: 100% unit-test coverage.** Every PR should maintain or improve coverage.
- Coverage drop = blocker.
- Integration/end-to-end tests separate from unit coverage metric.

---

## 15. Dependency Policy

- **Always upgrade to latest.** Dependabot configured aggressively (weekly minimum, daily acceptable). Push every dependency and module to its newest available version whenever possible.
- **Backwards compatibility is not a concern.** Do not hold back upgrades to preserve compat with older callers, older runtimes, older sibling repositories, or deprecated APIs. Bump, adapt call sites, move on. No compat shims, no version-guarded branches, no deprecated-API retention.
- **Tiebreaker — strict interdependency requirements.** When two newest versions conflict (e.g. lib A's latest needs lib B `<5`, lib B's latest is `6`), resolve by strict interdep constraints only. Pick the combination that satisfies hard requirements while keeping the rest of the graph as fresh as possible. Never pick an older version for any reason other than an unsatisfiable constraint.
- Pin to exact versions when ecosystem allows; avoid range operators (`^`, `~`, `>=`) in production manifests.
- **Lockfiles not committed.** Add to `.gitignore`: `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `poetry.lock`, `Gemfile.lock`, `Cargo.lock` (binary projects only — libraries follow Rust convention). Exceptions: Go `go.sum` (different semantics — commit), Python `uv.lock` (commit per §21).

---

## 16. Definition of Done

A change is **done** only when all of:

1. Target behavior achieved (feature works / bug fixed).
2. Formatted with canonical tool per §3.1 (run before commit).
3. Linted (super-linter clean).
4. Tested (coverage maintained at ~100% unit).
5. Docs updated. If repository has `docs/` folder (or external docs site), audit
   whether change impacts documented behavior, APIs, config, CLI flags, schemas, or
   examples. Update affected pages in same commit/PR. Stale docs block done.
6. **Local CI green before push.** Reproduce the repository's `push.yml` workflow
   locally per §22 and confirm every job that would fire on the pending push
   passes. Each amend-on-CI-failure (per §7) doubles Actions minutes consumption,
   so a remote run is not the first signal — local reproduction is. Push only
   after local green.
7. **Post-push CI green.** If pushed to a remote whose repository defines workflows
   triggered by `push` (check `.github/workflows/*.yml` for `on: push` — including
   branch filters matching the pushed ref), track the run kicked off by the push until
   it completes. Tail with `gh run watch` on the run for the pushed SHA, or poll
   `gh run list --branch <branch> --commit <sha>` until conclusion. On failure: surface
   logs (`gh run view --log-failed`), do not declare done. Fix locally, then
   `git commit --amend` (re-sign) and `git push --force-with-lease` — per §7.
   Re-track new run on amended SHA. On success: report run URL plus conclusion.
   Skip only if no `push`-triggered workflow matches the pushed ref.

Don't mark complete or commit otherwise.

---

## 17. AI / Generator Attribution

**Do not attribute commits to AI.** No `Co-Authored-By: <bot>`, no `Generated with <tool>` trailers, no AI mentions in commit/PR bodies. Commits author = human only.

---

## 18. Naming Preferences

When naming new repositories, services, packages, modules, or significant components, **prefer Ancient Latin** roots/words. Aim for short, evocative, semantically tied to function.

- Latin noun > Latin verb > English fallback.
- Avoid forced Latinizations of English terms — pick a real Latin word with fitting meaning instead.
- Single word preferred. Two-word combos only if one word doesn't capture intent.
- Propose 2–3 candidates with brief gloss (meaning + why it fits).

---

## 19. LICENSE

**GPL-3.0** universally. Every repository carries `LICENSE` at root with full GPL-3 text.

- New repositories: add GPL-3 LICENSE at init.
- Drift: any repository missing LICENSE → add GPL-3.
- Exception: repositories vendoring upstream code under incompatible license (e.g. forks of GPL-2-only or BSD projects) keep upstream license — preserve original `LICENSE`, add secondary license file (`LICENSE.<name>`) only if combining with new GPL-3 code.
- Rationale: aligns with copyleft-required deps and protects derivative works. All other transitive deps in current repositories are permissive (MIT/BSD/Apache-2.0) and GPL-3-compatible.

---

## 20. Drift Detection Heuristics

When auditing repositories, look for:

- `README.md` at root instead of `.github/README.md`.
- Readme longer than ~3 lines or with install/badges/usage sections (deviates from minimal template).
- Sprawling root directory — files belonging in `.github/`, `.config/`, or lang-idiomatic subdirs.
- Default branch ≠ `master`.
- Branch names not following `feat/` convention.
- Unsigned commits in recent history.
- Workflow file ≠ `push.yml` / `tag.yml` for primary CI / release. Presence of `lint.yml`, `ci.yml`, `test.yml`, `release.yml` = drift; collapse into `push.yml` or `tag.yml`.
- Missing `super-linter` workflow, or super-linter with non-default overrides lacking justification.
- Code not formatted with canonical tool per §3.1 (e.g. Go file not `gofumpt`-clean, Python not `ruff format`-clean, JS/TS not `prettier`-clean).
- Multiple competing formatters configured per language in same repository (e.g. both `black` and `ruff format`, or both `prettier` and `biome`).
- CI workflows without `paths-filter` despite multi-component layout.
- Hardcoded versions/tags/image names in workflows, or `env` aliases re-aliasing exposed `${{ github.* }}` context.
- Docker image references in workflows hardcoding owner/repository
  (`ghcr.io/myorg/myapp`) instead of deriving from `${{ github.repository }}` /
  `${{ github.repository_owner }}` (§5.1).
- Docker push publishing only one tag — missing `:latest`/SHA pair on `push.yml`,
  or missing `:release`/`${{ github.ref_name }}`/SHA triple on `tag.yml` (§5.2).
  Single floating tag with no immutable companion = no provenance; single
  immutable tag with no convenience pointer = no consumer ergonomics. `:latest`
  pushed from `tag.yml` (or `:release` pushed from `push.yml`) = mutable-pointer
  crossover, also drift.
- Publish steps (`docker push`, `npm publish`, `gh release create`, `terraform apply`, etc.) reachable from `pull_request` triggers without an event-gate (§11.1). `pull_request_target` used to grant write tokens to PR code = critical antipattern.
- Dockerfile using non-Alpine base when Alpine variant exists and no documented blocker (§5.3). Toolchain image as final stage = drift. Build-only deps left in final layer = drift. Floating/major-only base tag = drift. Missing `.dockerignore` = drift. Root user in final stage = drift.
- Docker build job using `docker/setup-qemu-action`, `platforms:` containing anything other than bare `linux/arm64`, or running on `ubuntu-latest` instead of `ubuntu-24.04-arm` (§5.4). Multi-arch fan-out via QEMU on x86 runner = critical drift; native arm64 runner mandatory.
- Docker build job missing `cache-from: type=gha` / `cache-to: type=gha,mode=max` (§5.5). Multi-image repository missing per-image `scope=<name>` qualifier = drift.
- `push.yml` missing top-level `concurrency:` block, or `cancel-in-progress: false`, or group expression not `${{ github.workflow }}-${{ github.ref }}` (§11.2). `tag.yml` with `cancel-in-progress: true` (releases must finish) = drift.
- Missing `.github/dependabot.yml`, or dependabot missing ecosystems present in repository.
- Non-Conventional commit messages in recent history.
- Commit subjects with punctuation/symbols beyond the `type(scope):` separator — parentheses, brackets, slashes, quotes, backticks, em-dashes, lists, multi-clause "X and Y" enumerations (§7).
- Verbose commit bodies restating the diff.
- Commit body lines >100 chars (commitlint `body-max-line-length` default).
- "fix CI" / "fix lint" / "address review" trailing fixup commits in recent history — should have been amended into the failing commit (§7).
- Linter / formatter config files (`.golangci.yml`, `.eslintrc*`, `biome.json`, `commitlint.config.js`, `.codespellrc`, etc.) at repository root or scattered, instead of consolidated under `.github/linters/` with root symlinks for tools that require root discovery (§3.3).
- super-linter step missing performance env knobs from §3.2 (`SAVE_SUPER_LINTER_OUTPUT: false`, `MULTI_STATUS: false`, `LOG_LEVEL: WARN`), or using non-`slim` variant.
- Lockfiles committed (except `go.sum` and `uv.lock`).
- Dependencies pinned below latest available without an unsatisfiable interdep constraint forcing it (§15). Compat-driven version holds = drift.
- Coverage <100% on unit tests.
- Presence of `CHANGELOG.md` (should not exist).
- Presence of `pre-commit`/`husky`/`lefthook` config (should not exist).
- AI co-author trailers in commit history (should not exist).
- Tag format ≠ `vX.Y.Z`.
- Inconsistent action pinning (mix of SHA vs tag vs major version).
- Missing or inconsistent `LICENSE` file across repositories (expected: GPL-3 unless vendoring exception).
- Lang layout violations (e.g. Go repository with `src/`, Python repository flat-layout when src-layout expected).

Surface as **drift report**, not autofix.

---

## 21. Python Project Standard

All Python projects across all repositories follow this scheme. No exceptions for "small scripts" — if it has a `.py` file deployed or shipped, it has a `pyproject.toml`.

### 21.1 Manifests

- **Required**: `pyproject.toml` (PEP 621).
- **Forbidden**: `requirements.txt`, `requirements-*.txt`, `setup.py`, `setup.cfg`, `Pipfile`, `Pipfile.lock`, `poetry.lock`. Migrate or delete on sight.
- **Build backend**: `hatchling` (default). Other backends require justification.

### 21.2 Resolver, Runner, Lockfile

- **Tool**: `uv` only. No `pip install`, no `poetry`, no `pipenv` in workflows or docs.
- **Lockfile**: `uv.lock` committed per project (one per `pyproject.toml`). Overrides §15 lockfile-ignore default.
- **Install**: `uv sync --frozen` (CI) / `uv sync` (dev).
- **Run**: `uv run python <script>` or `uv run <entrypoint>`. Never bare `python`.

### 21.3 Python Version

- **Floor**: latest stable Python (currently `>=3.13`). Bump when next minor lands and tooling catches up.
- **Pin**: `requires-python = ">=3.13"` in `pyproject.toml` + `.python-version` file at project root for `uv python install` resolution.

### 21.4 Layout

- **Tool runner** (single-file CLI under `unciae/<category>/<tool>/`): flat — `main.py` + `pyproject.toml` + optional `__init__.py` adjacent. Wheel exposed via `[tool.hatch.build.targets.wheel] force-include`.
- **Library** (reusable, importable across repos): flat at category root (e.g. `unciae/<category>/<lib>/{api.py,__init__.py,pyproject.toml}`) or `src/<pkg>/` for non-trivial libs.
- **App** (deployed service, e.g. `serica`): `src/<pkg>/` layout, `[project.scripts]` for entrypoints.
- **Build tool** (e.g. `streambinder`, `erro` `.make/`): keep `.make/` directory; expose via `[tool.hatch.build.targets.wheel] packages = [".make"]` (rename via `[tool.hatch.build.targets.wheel.sources]` if dot-prefix breaks import).

### 21.5 Naming

- Project `[project] name` is bare `<pkg>` — no `unciae-` or repo-prefix. Collisions inside the monorepo are not expected since each `unciae/<category>/<tool>/` is unique.
- PyPI namespace collision is not a concern (packages are not published). `[tool.uv.sources]` overrides any same-name PyPI lookup.

### 21.6 Cross-Project Dependencies (Git Sources)

Pure Git references — no PyPI, no private index, no path deps in committed manifests.

```toml
[project]
dependencies = ["immich"]

[tool.uv.sources]
immich = { git = "https://github.com/streambinder/unciae.git", tag = "v0.42.0", subdirectory = "media/immich" }
```

- **Tag**: repository-wide `vX.Y.Z` (per §10) — no per-package tag prefix. Bumping any library in a repository requires a repository tag bump; consumers re-resolve on next `uv lock`.
- **`uv.lock` pins resolved SHA** regardless of `tag` / `branch` source — reproducibility guaranteed.
- **Local dev override**: gitignored `uv.toml` next to consumer's `pyproject.toml` with `[sources] <pkg> = { path = "...", editable = true }`. Never commit path sources.

### 21.7 Type Annotations

- **Target**: full type annotations on every function, method, and module-level binding. Public and private alike.
- **`from __future__ import annotations`** at top of every `.py` file.
- **`Any`** requires inline justification comment.
- **CI**: `uv run mypy --strict .` (or `ty` once stable from astral). No untyped escape hatches via `# type: ignore` without comment explaining why.
- **Migration grace period**: pre-existing projects migrating to this scheme MAY commit phase-1 (tooling: pyproject.toml + uv.lock + ruff) before phase-2 (full annotations + strict mypy). Phase-1 commits MUST set `[tool.mypy] strict = false` with a comment naming phase-2 as follow-up. New projects MUST land both phases atomically.

### 21.8 Lint & Format

- **Tool**: `ruff` only — single tool for both. No `black`, no `isort`, no `flake8`, no `pylint`.
- **CI gates**: `uv run ruff check .` + `uv run ruff format --check .`.
- **Config**: single `.github/linters/.ruff.toml` per repository (per §3.3 — super-linter consumes it). Do NOT put `[tool.ruff]` in per-package `pyproject.toml` — it would be ignored by super-linter and cause CI/local drift.

### 21.9 CI Gates (per `push.yml`)

For Python paths-filter match, run in order:

1. `uv lock --check` — lockfile in sync with manifest
2. `uv sync --frozen` — installs cleanly
3. `uv run ruff check .`
4. `uv run ruff format --check .`
5. `uv run mypy --strict .`
6. `uv run pytest` (if tests present)

### 21.10 Bootstrap Behavior (clavis / imperium)

When a Python tool is materialized on a host:

- **Detect** `pyproject.toml` adjacent to `main.py`.
- **Hard fail** if `main.py` exists without `pyproject.toml`. No fallback to `requirements.txt`, no fallback to bare symlink.
- **Install**: `uv sync --frozen` in tool directory.
- **Wrapper**: generated shim script `exec uv --project <dir> run python <dir>/main.py "$@"`.

### 21.11 Migration Drift Signals

Add to §20 audit list:

- Presence of `requirements.txt`, `setup.py`, `Pipfile`, `poetry.lock` — migrate to `pyproject.toml` + `uv.lock`.
- `pyproject.toml` without `uv.lock` adjacent.
- `pyproject.toml` without `requires-python = ">=3.13"` (or current floor).
- Python source file without type annotations or without `from __future__ import annotations`.
- CI workflow invoking `pip`, `poetry`, `pipenv`.
- Path source (`{ path = ... }`) committed in `pyproject.toml` (allowed only in gitignored `uv.toml` overrides).

---

## 22. Local CI Reproduction — Pre-Push Discipline

Every push that fails CI costs Actions minutes twice: once for the failing run, once for the re-run after `--amend` + `--force-with-lease` (mandated per §7). Multiply by branch lifetime and the burn dwarfs the cost of running the same checks locally first. **Reproduce CI locally before every push.** Push only on local green.

### 22.1 Tooling Hierarchy

Pick the cheapest tool that exercises the failing surface. Escalate only when a cheaper layer can't reproduce the failure.

1. **Native CLI** — direct invocation of the underlying tool (`gofumpt -l -e .`, `uv run mypy --strict`, `flutter analyze`, `cargo fmt --check`, `prettier --check .`). Fastest, no container overhead. Use for single-language checks where the workflow step is a thin wrapper around the CLI.
2. **`super-linter` standalone container** — pull `ghcr.io/super-linter/super-linter:slim-v8` (or the SHA pinned in `push.yml`), mount repository at `/tmp/lint`, set `RUN_LOCAL=true` + same `VALIDATE_*` env as the workflow. Reproduces the exact lint matrix without spinning a runner. Use when super-linter is the failing job and native CLI doesn't cover the linter (e.g. `commitlint`, `jscpd`, `gitleaks`).
3. **`act`** — runs the workflow YAML in a runner-like container. Most faithful reproduction; handles paths-filter, secrets, multi-job dependency graph. Use when the failing job is composite (setup-go + cache + custom script), when interaction between jobs matters, or when a non-super-linter job needs validation. Slowest and heaviest — last resort, not first.

### 22.2 `act` Setup (Canonical)

- **Install**: `brew install act` (macOS), `gh extension install nektos/gh-act` (cross-platform via gh).
- **Global config** at `~/.actrc`:
  - Pin runner image `ghcr.io/catthehacker/ubuntu:act-latest` for `ubuntu-latest` (medium image — ships node/python/go/Docker preinstalled; small image lacks tooling super-linter needs).
  - Force `--container-architecture linux/amd64` on Apple Silicon hosts (GitHub-hosted runners are amd64; QEMU emulation cost is acceptable vs. CI-minute burn).
  - `--pull=false` to skip registry hits after first pull.
- **Per-repo `.secrets`** — gitignored (globally via `~/.config/git/ignore`, never per-repo `.gitignore` — keeps repository `.gitignore` clean). Minimum: `GITHUB_TOKEN=$(gh auth token)`. Add other `secrets.*` referenced by jobs you intend to exercise locally.
- **Default event = `pull_request`**. Every `push.yml` in this monorepo gates publish/notify jobs with `if: github.event_name == 'push' && github.ref == 'refs/heads/master'` (per §11.1) — so `act pull_request` runs only the cheap validation half. Reserve `act push` for rehearsing master-only deploy paths.

### 22.3 Pre-Push Workflow

Before every `git push`:

1. Identify the jobs in `push.yml` that the change would trigger (consult `paths-filter` block; mirror the globs).
2. Run each in cheapest-tool order per §22.1.
3. On failure: fix, `git commit --amend` (per §7 — same rule applies before push as after), re-run locally. Repeat until green.
4. Push only on local green.

### 22.4 What Not to Do

- **Don't skip local CI because "it'll probably pass"**. The amend cycle cost is the same regardless of intent; locally validating is always cheaper than the second remote run.
- **Don't install pre-commit / pre-push framework hooks** (per §13). Plain shell hook in `.git/hooks/pre-push` allowed if you want auto-invocation, but it lives outside the repository — don't propose checking it in.
- **Don't skip jobs that QEMU makes slow** (multi-arch Docker buildx, Flutter on M1). Run the single-arch / native variant locally; trust CI for the multi-arch fan-out (those steps are master-gated and run once, not per amend).
- **Don't disable jobs in `push.yml` to make local easier**. The CI matrix is the source of truth; local tooling adapts to it.

### 22.5 Drift Signals (add to §20)

- Recent `master` history shows fixup commits with subjects like `fix(ci):`, `fix(lint):`, `chore: format` — symptom of pushing without local CI run, then amending.
- Repository accumulates `.github/workflows/*.yml` that have no documented local-reproduction path (native CLI, super-linter env, or `act` job filter). Every CI job should be runnable locally; if it isn't, that's the gap to close.
- Contributor docs (per-repo `CONTRIBUTING.md` or `README`) reference "push and check CI" as the validation step instead of local reproduction.

---
