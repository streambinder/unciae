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
- Allowed at root: `LICENSE`, `.gitignore`, manifests
  (`go.mod`, `package.json`, `pyproject.toml`, `pubspec.yaml`),
  `.github/`.
- > ~8 visible entries → propose move.
- `AGENTS.md` lives only in this repository, as the single canonical
  standard. Other repositories carry no `AGENTS.md`: a specialized
  copy drifts from the standard. One exception: `oilercorp/*`, whose
  `AGENTS.md` serves its human team, not the standard reader.
- `.editorconfig` is not committed. Editor configuration is a local
  property of the checkout of the contributor, not of the repository.

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

All super-linter configs live under `.github/linters/`. A linter config is
never committed at the repository root, not even as a symlink. If a tool
requires its config at the root, the CI workflow links or copies it there
during the run only. Never duplicate.

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
minor/patch. Enable Dependabot alerts on every repository.

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
- Merge a pull request with the rebase and merge method. Never
  create a merge commit.
- Tags `vMAJOR.MINOR.PATCH` SemVer, no `v0` perpetual
- `push.yml` on branch pushes only (never `pull_request`), `tag.yml` on `v*` creates release
- No CHANGELOG file, use GitHub auto notes.

## 11. CI Workflows

Two canonical: `push.yml` and `tag.yml` (`v*`). Others allowed
if single-purpose (`dependabot-auto-merge.yml`, `codeql.yml`).

`push.yml` triggers on branch pushes only, never on `pull_request`:

```yaml
on:
  workflow_dispatch: null
  push:
    branches: ["**"]
```

A `pull_request` trigger duplicates every run of a PR branch: the push run
on `refs/heads/<branch>` and the PR run on `refs/pull/<n>/merge` carry
different refs, so the concurrency group cannot collapse them, and
Actions minutes roughly double. PRs still get their checks from the push
run on the branch head commit. Tag pushes stay out of `push.yml`:
`tag.yml` owns `v*`. The push run on master is the safety net for merged
trees: it tests the merge result right after the merge and gates
publication on it.

### 11.1 Publish gating

Publish steps (image push, npm/pip publish, `gh release`, `terraform apply`)
are gated on the ref, never on the event: `:latest` only from
`refs/heads/master`, releases only from `tag.yml` on `v*`. A container
image push to the `${{github.sha}}` tag is allowed on any branch to
validate the build. Never `pull_request_target`.

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

Write unit tests next to the code that the tests cover.

- Name the test file after the module: `module_test.ext` or
  `test_module.ext`. Follow the naming convention of the language.
- A framework or a toolchain may dictate a different test layout.
  Follow the layout that the framework or the toolchain dictates.
  The exception covers the layout only. The other rules of this
  section still apply.
- Integration and end-to-end tests live separately from unit tests.
- CI runs the unit tests on every push. A failing test blocks the merge.
- CI measures unit test coverage on every push. The minimum coverage
  is 90%.
- Coverage below 90% blocks the merge.
- Non-test code never changes to satisfy a test. Change the test
  instead.

## 16. Dependencies

Always upgrade to latest. Weekly Dependabot, daily OK. Backwards compat not a
concern — bump, adapt, move on. Pin exact versions where possible, avoid
`^~>=` in prod. Tiebreaker: newest versions satisfying hard constraints only.

### 16.1 Library Selection

Minimize the code surface that the repository owns and maintains.

- Write in-house only functionality that belongs to the product logic.
- For other functionality, simplify the problem away when possible.
- When simplification is not viable, delegate to a specialized library.
- A small and self-contained helper may stay in-house.
- Select libraries with an established reputation: active maintenance,
  wide adoption, a verifiable track record.
- Do not adopt an obscure or unmaintained library to avoid a small amount
  of in-house code.
- Every adopted library follows the update rules of §6 and §16.

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

## 22. Writing Standard

All technical writing follows ASD-STE100. Scope: documentation, readme files,
pull request descriptions, commit message bodies. The rules do not apply to
code and to quotations. In design and planning documents only rule 4 applies;
sentence length limits do not apply.

1. Keep sentences short: maximum 20 words in a procedure, 25 in a description.
2. Write one instruction in each sentence.
3. Use the active voice.
4. Use one term for one concept. Do not use synonyms for the same concept.
5. Do not use a pronoun when its reference is not clear.
6. Use a verb to describe an action. Do not hide an action in a noun phrase.

Authors apply the rules when they write. Reviewers check the rules when they
review. No automated checker enforces this section.

If the context requires another language, use that language and apply the same
principles to it.

## 23. Consistency and Readability

Code and configuration must read as if one hand wrote the file.

- Infer the conventions of the file and of the codebase. Apply the
  conventions that you infer.
- Conventions include block separation, naming, ordering, indentation and
  comment style.
- Apply each convention to the whole file. Do not mix two conventions in
  one file.
- When no convention exists, choose for readability first and for
  compactness second.
- A change follows the conventions of the file that the change touches.
  Do not reformat parts that the change does not touch.

## 24. Verification Subjects

A change is often verified against real subjects: real people, real
accounts, real services, real data.

- Commit messages and pull request descriptions must not name a
  verification subject.
- Do not include the name, the handle, the email address, the domain,
  the profile URL, or any other identifier of a verification subject.
- Describe the verification in generic terms: the class of the subject
  and the outcome of the verification.
- The rule applies to public repositories and to private repositories.
  Commit history is permanent, and a description is republished with
  every mirror and fork.

## 25. Specification-Driven Development

Every feature is specified before the feature is implemented. The
specification, the plan, and the record of the work live in the
repository. Each kind of information has one authoritative place.

- A feature change runs a specification cycle. The cycle has six
  steps: specify, plan, tasks, implement, verify, converge.
- The specify step produces a specification. The specification states
  what the feature does and why the feature exists. The specification
  contains user stories, functional requirements, and success
  criteria. The specification contains no implementation detail.
- A feature request is a hypothesis. The specify step opens with
  an investigation of the hypothesis on real data.
- The investigation verifies that the problem exists. The
  investigation verifies that the assumed cause holds. The
  investigation looks for a simpler alternative.
- The investigation has three outcomes: specify the feature as
  proposed, specify a different solution, or abandon the feature.
  Abandonment closes the cycle before the plan step.
- The decision register records the outcome of the investigation
  and the evidence of the investigation. The specification is a
  draft until the owner ratifies the specification. The plan step
  starts after the ratification of the specification.
- The plan step produces a technical plan. The plan shows how the
  change satisfies this standard. The tasks step derives an ordered
  task list from the plan.
- The converge step closes the artifacts of the feature. A completed
  feature directory is an immutable historical record.
- The artifacts of a feature live in `specs/NNN-<short-name>/` at the
  repository root. NNN is a zero-padded sequence number.
- A significant decision goes to a decision register. The register
  holds one file per decision, in MADR format. A decision is a draft
  until the owner ratifies the decision. An accepted decision is
  reused. A superseded decision stays in the register and names the
  successor of the decision.
- Each project carries a constitution. The constitution states the
  rules that are specific to the project. The constitution derives
  every other rule from this standard. This standard prevails when a
  constitution and this standard conflict.
- Adoption of this section is complete only under one condition. A
  new session resumes the work from the repository files alone. The
  session completes a scoped change and shows the verifications of
  the change.
- The cycle binds feature changes and changes to the domain model. A
  bugfix and a small change do not run the cycle. The body of the
  pull request states the rationale of the fix or of the change.
- A project adopts this section at creation. An existing project
  adopts this section at the next feature change of the project.
- A pull request of the cycle holds one commit or more. One
  commit stays the preference.
- Each file the pull request changes appears in exactly one
  commit of the pull request.
- A specification pull request holds one commit.
- An implementation pull request holds one commit per plan
  phase. A small change holds one commit.
- A fix to a commit amends that commit. The fix never opens a
  new commit.
- GitHub Spec Kit is the reference implementation of this section.
  Lint excludes the files that the tool manages, through targeted
  rules only. Nobody edits a managed file by hand. A project that
  replaces the tool records the replacement as a decision.
