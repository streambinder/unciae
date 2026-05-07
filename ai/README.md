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

### 3.2 Linter / Formatter Config Location

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
- **Body line length ≤100 chars.** Matches `commitlint` `body-max-line-length` default. Hard-wrap longer lines. Includes URLs — break or shorten.
- One logical change per commit. No "misc fixes".
- PR title = top commit subject.
- Per-repository `commitlint` config aligned with above (suggest adding if missing).

---

## 8. Language Code Layout

Respect language-idiomatic layout. **Do not force uniform `src/` across all stacks.**

| Lang             | Layout                                                                                                                                   |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Go               | [Standard Go Project Layout](https://github.com/golang-standards/project-layout): `cmd/`, `internal/`, `pkg/`, flat packages — no `src/` |
| TS/JS (lib)      | `src/` + `dist/`, ESM, `package.json` `exports` field                                                                                    |
| TS/JS (Node app) | `src/`, `tests/`, build to `dist/`                                                                                                       |
| Python           | [src-layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/): `src/<pkg>/`, `tests/`, `pyproject.toml`    |
| Dart/Flutter     | `lib/`, `test/`, `assets/`, idiomatic Flutter structure                                                                                  |
| Rust             | Cargo conventions: `src/`, `tests/`, `examples/`                                                                                         |

Tests live alongside or in idiomatic test directory per lang — pick one per repository, stay consistent.

---

## 9. Language Conventions

- **Go**: `gofumpt`-clean, `any` over `interface{}`, errors wrapped with `%w`, table-driven tests.
- **TS**: strict mode, no `any` without comment, ESM, no default exports for libs.
- **Python**: type hints on public API, `ruff` defaults, `pyproject.toml` not `setup.py`.
- **Dart**: null-safety, `const` constructors, `flutter_lints` baseline.

---

## 10. Branching & Releases

- **Primary branch**: `master`. Never assume `main`.
- **Feature branches**: `feat/<short-name>`. Catch-all prefix — covers fixes, chores, docs too unless context strongly justifies different prefix.
- **Signed commits**: **always**. Every commit GPG/SSH-signed.
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

---

## 12. Readme Convention

Repositories use a **minimal readme**. Detailed docs live elsewhere (external site, `docs/`, or upstream project).

Canonical template (root or `.github/`):

```markdown
# <RepoName> <a href="<docs-url-or-repo-url>"><img alt="documentation" align="left" src="<owner-avatar-url>"></a>

<one-line description OR "Documentation available at [<host>](url)." OR "Documentation not available yet.">
```

- Title-case repository name (Unicode OK).
- Anchor logo image links to docs site if exists, else upstream/repository URL.
- Body = single line. No install/usage/badges sections — those belong on docs site.
- If `docs/` folder exists locally, link to hosted version.

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

- **Always upgrade to latest** where compatible. Dependabot configured aggressively (weekly minimum, daily acceptable).
- Pin to exact versions when ecosystem allows; avoid range operators (`^`, `~`, `>=`) in production manifests.
- **Lockfiles not committed.** Add to `.gitignore`: `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `poetry.lock`, `uv.lock`, `Gemfile.lock`, `Cargo.lock` (binary projects only — libraries follow Rust convention). Go `go.sum` is exception (commit it — different semantics).

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
6. **Post-push CI green.** If pushed to a remote whose repository defines workflows
   triggered by `push` (check `.github/workflows/*.yml` for `on: push` — including
   branch filters matching the pushed ref), track the run kicked off by the push until
   it completes. Tail with `gh run watch` on the run for the pushed SHA, or poll
   `gh run list --branch <branch> --commit <sha>` until conclusion. On failure: surface
   logs (`gh run view --log-failed`), do not declare done. On success: report run URL
   plus conclusion. Skip only if no `push`-triggered workflow matches the pushed ref.

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
- Missing `.github/dependabot.yml`, or dependabot missing ecosystems present in repository.
- Non-Conventional commit messages in recent history.
- Commit subjects with punctuation/symbols beyond the `type(scope):` separator — parentheses, brackets, slashes, quotes, backticks, em-dashes, lists, multi-clause "X and Y" enumerations (§7).
- Verbose commit bodies restating the diff.
- Commit body lines >100 chars (commitlint `body-max-line-length` default).
- Linter / formatter config files (`.golangci.yml`, `.eslintrc*`, `biome.json`, `commitlint.config.js`, `.codespellrc`, etc.) at repository root or scattered, instead of consolidated under `.github/linters/` with root symlinks for tools that require root discovery (§3.2).
- Lockfiles committed (except `go.sum`).
- Coverage <100% on unit tests.
- Presence of `CHANGELOG.md` (should not exist).
- Presence of `pre-commit`/`husky`/`lefthook` config (should not exist).
- AI co-author trailers in commit history (should not exist).
- Tag format ≠ `vX.Y.Z`.
- Inconsistent action pinning (mix of SHA vs tag vs major version).
- Missing or inconsistent `LICENSE` file across repositories (expected: GPL-3 unless vendoring exception).
- Lang layout violations (e.g. Go repository with `src/`, Python repository flat-layout when src-layout expected).

Surface as **drift report**, not autofix.
