# AGENTS — Repository Standard

Universal standard for all my repositories. Stack agnostic. Suggestions, not
hard rules. Surface drift, propose alignment, owner decides.

Per-repository `CLAUDE.md` or local `AGENTS.md` addition overrides this file
when explicitly documented.

---

## 1. General Principles

- One repository — one deployable unit (or tightly coupled set). Hard boundary.
- Minimize root clutter. Prefer conventional locations over ad-hoc files.
- CI is source of truth. Local checks mirror CI, never replace it.
- Prefer latest dependencies, native arm64, immutable tags.

## 2. Root Hygiene

- Move that can live elsewhere out:
  - `Readme.md` → `.github/README.md`
  - `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, templates → `.github/`
  - Configs → `.config/`, `tools/` or language native
- Allowed at root: `LICENSE`, `.gitignore`, `AGENTS.md`, manifests
  (`go.mod`, `package.json`, `pyproject.toml`, `pubspec.yaml`),
  `.editorconfig`, `.github/`.
- > ~8 visible entries → propose move.

## 3. Linting — super-linter

`super-linter` is the default linter via GitHub Actions, job inside
`.github/workflows/push.yml`, not separate `lint.yml`. Use defaults. Override
only with justification in workflow comment. Covers secret scanning.

### 3.1 Canonical Formatters

Format with same tool super-linter ships before commit/push/test. One tool per
language.

- Go: `gofumpt -w .` — `FIX_GO`
- Python: `ruff format . && ruff check --fix .` — `FIX_PYTHON_*`
- JS/TS: `prettier -w . && eslint --fix .` — `FIX_*_PRETTIER,ES`
- JSON/YAML/MD/CSS/HTML: `prettier -w .`
- Shell: `shfmt -w .`
- Rust: `cargo fmt && cargo clippy --fix`
- Dart: `dart format .`
- Terraform: `terraform fmt -recursive`

### 3.2 super-linter Performance

Use `slim` variant. Required env: `SAVE_SUPER_LINTER_OUTPUT=false`,
`MULTI_STATUS=false`, `LOG_LEVEL=WARN`. Disable `VALIDATE_*` only when another
job already covers it, comment which job. `VALIDATE_ALL_CODEBASE=true` on
master push, false on PR.

### 3.3 Config Location

All super-linter configs live under `.github/linters/`. Tools that demand root:
keep canonical in `.github/linters/`, symlink from root
(`ln -sf .github/linters/...`). Never duplicate.

## 4. CI paths-filter (multi-component only)

For repositories with multiple components, use `dorny/paths-filter`. One
`changes` job, outputs per component, downstream `needs: changes` +
`if: needs.changes.outputs.xxx == 'true'`. Single component repositories skip
this.

## 5. Workflow Hygiene

Never hardcode versions, tags, image names that exist in GitHub context. Use
`github.*` directly, not via `env`. Define `env` only for true custom values.
Pin actions by SHA.

### 5.1 Container Image Names

Derive owner/repository from `github.repository`, never hardcode. GHCR default.

- Bad: `ghcr.io/myorg/myapp:${{github.sha}}`
- Good: `ghcr.io/${{github.repository}}:${{github.sha}}`

Multi-image: suffix off repository, e.g.
`ghcr.io/${{github.repository}}/backend`.

### 5.2 Container Tags

Every push to `master` publishes at least `:latest` + `${{github.sha}}` same digest.

```yaml
tags: |
  ghcr.io/${{github.repository}}:latest
  ghcr.io/${{github.repository}}:${{github.sha}}
```

PRs and feature branches may publish only `${{github.sha}}` to avoid polluting `:latest`:

```yaml
tags: |
  ghcr.io/${{github.repository}}:${{github.sha}}
```

Tag releases (`tag.yml`): `:release`, `:${{github.ref_name}}`,
`:${{github.sha}}`. Never push `:latest` from `tag.yml`.

### 5.3 Container Base Images

Prefer Alpine: `python:*-alpine`, `node:*-alpine`, `golang:*-alpine`.

- Multi-stage, final on minimal runtime, no toolchain in final
- Single `RUN apk add --no-cache` with cleanup same layer
- `--no-cache`, `pip --no-cache-dir`, `npm ci --omit=dev`
- Pin exact tag, not floating
- Non-root user final, `.dockerignore` present

Document exception if Alpine not viable.

### 5.4 Build Target — linux/arm64 Only

All images target `linux/arm64` exclusively. All deploy hosts are arm64.

- `platforms: linux/arm64` (bare, not `arm64/v8`)
- `runs-on: ubuntu-24.04-arm` native, never `setup-qemu-action`
- Multi-arch exception: split jobs, never QEMU.

### 5.5 Architecture — arm64 Everywhere

CI, tests, builds, images run on arm64 natively (`ubuntu-24.04-arm`). No
`ubuntu-latest` amd64 unless tool has no arm build, and then document exception
in workflow comment.

### 5.6 Docker Cache

<!-- textlint-disable terminology -->

Every `docker/build-push-action` must set:

```yaml
cache-from: type=gha
cache-to: type=gha,mode=max
```

<!-- textlint-enable terminology -->

Multi-image: add `scope=<name>`.

## 6. Dependabot

Required `.github/dependabot.yml` for all ecosystems present. Weekly, grouped
minor/patch.

## 7. Commits & PRs

- Conventional Commits: `type(scope): subject` — types
  `feat|fix|refactor|chore|docs|test|ci|perf|build`
- Subject ≤72, imperative, no period, plain phrase — no `()[]"'``/,:;` inside.
- Body ≤1 short paragraph, optional. Single sentence, plain prose, ends with
  period, ≤100 chars. Explain why, not what.
- One logical change per commit. No `CHANGELOG`.
- PR title = top commit subject.
- **Fixup on CI fail: amend, never new commit.**
  `git commit --amend`, `push --force-with-lease`. Applies to master too.
- Signed commits always.

## 8. Language Layout

Respect idiomatic layout, do not force `src/` everywhere.

- Go: `cmd/`, `internal/`, `pkg/`
- TS/JS lib: `src/` + `dist/` ESM
- TS/JS app: `src/`, `tests/`
- Python: `src/<pkg>/`, `tests/`, `pyproject.toml` (single-file runner:
  `main.py` + `pyproject.toml` flat per §12)
- Dart/Flutter: `lib/`, `test/`, `assets/`
- Rust: `src/`, `tests/`, `examples/`

## 9. Language Conventions

- Go: `gofumpt`, `any`, errors `%w`, table tests
- TS: strict, no `any` without comment, ESM, no default export for libs
- Python: see §12 — `uv`, full types, `ruff` + `mypy --strict`
- Dart: null-safety, `const` ctors, `flutter_lints`

## 10. Branching & Releases

- Primary: `master`, never assume `main`
- Feature branches: `feat/<short-name>` (covers fix/chore/docs too)
- Signed commits always, `pull.rebase = true`
- Tags `vMAJOR.MINOR.PATCH` SemVer, no `v0` perpetual
- `push.yml` on master + PRs, `tag.yml` on `v*` creates release
- No CHANGELOG file, use GitHub auto notes.

## 11. CI Workflows

Two canonical: `push.yml` (master + PRs) and `tag.yml` (`v*`). Others allowed
if single-purpose (`dependabot-auto-merge.yml`, `codeql.yml`).

### 11.1 Publish Never on PR

Publish steps (image push, npm/pip publish, `gh release`, `terraform apply`)
must be gated `if: github.event_name != 'pull_request'` or trigger only
`tags: ['v*']`. Exception: container image push to `${{github.sha}}` tag only
is allowed in PRs and feature branches to validate build, never `:latest` or
`:release`. Never `pull_request_target`. Secrets for publish never
referenced in PR-reachable steps.

### 11.2 Concurrency

Every `push.yml` must:

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

`tag.yml`: group `${{github.workflow}}-${{github.ref_name}}`,
`cancel-in-progress: false`.

## 12. Python Standard

All Python projects: `pyproject.toml` only, no
`requirements.txt`/`setup.py`/`Pipfile`/`poetry.lock`. Tool `uv` only,
`uv.lock` committed. Floor `>=3.13` + `.python-version`. Layout: runner flat
`main.py`+`pyproject.toml`, library `src/<pkg>/` or flat, app `src/`.

<!-- textlint-disable terminology -->

Dependencies via pure Git:

```toml
[tool.uv.sources]
pkg = { git = "https://github.com/streambinder/unciae.git", tag = "vX.Y.Z", subdirectory = "..." }
```

<!-- textlint-enable terminology -->

Types: full annotations, `from __future__ import annotations`, `mypy --strict`.
Lint: `ruff check` + `ruff format --check`, config in
`.github/linters/.ruff.toml`. CI: `uv lock --check`, `uv sync --frozen`, ruff,
mypy, pytest.

## 13. Readme

Minimal: title + one-liner from manifest or `Documentation available at
<url>.` No install/badges/usage. Full docs live in `docs/` or external site.

## 14. Pre-commit

No local framework (`pre-commit`, `husky`). CI is source of truth.

## 15. Testing

Target 100% unit coverage. Coverage drop = blocker. Integration/end-to-end
separate.

## 16. Dependencies

Always upgrade to latest. Weekly Dependabot, daily OK. Backwards compat not a
concern — bump, adapt, move on. Pin exact versions where possible, avoid
`^~>=` in prod. Tiebreaker: newest versions satisfying hard constraints only.
Lockfiles ignored except `go.sum` and `uv.lock` (commit per §12).

## 17. Definition of Done

Done only when: feature works, formatted (§3.1), linter clean, coverage kept,
docs updated if needed, local CI green before push per §18, post-push CI green
(`gh run watch`).

## 18. Pre-Push

Reproduce CI locally before push with cheapest tool (`gofumpt -l`,
`uv run mypy`, `prettier --check`). `super-linter` container second, `act`
last resort. Do not push on red.

## 19. AI Attribution

Do not attribute to AI — no `Co-Authored-By: <bot>` trailers.

## 20. Naming

For new repositories/services/packages, prefer Latin roots — short, evocative.

## 21. LICENSE

GPL-3.0 universally, `LICENSE` at root.
