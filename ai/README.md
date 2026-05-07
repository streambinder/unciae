# Canon — Repository Guidelines

Universal guidelines for repositories under this meta-repo. Stack-agnostic, tooling-agnostic where possible. Intended as durable reference for **any** AI assistant, code generator, contributor, or future-self consulting standards.

These are **suggestions**, not enforced rules. Surface drift; propose alignment; let owner decide.

---

## 1. Repo Topology

Each top-level directory in the meta-repo is an independent git repository. Each repo has its own `.git`, history, remote, CI. Treat repo boundary as hard — no cross-repo automation without explicit intent.

A per-repo `CLAUDE.md` / `AGENTS.md` / equivalent overrides these guidelines for that repo.

---

## 2. Repo Root Hygiene

**Root path stays minimal.** Move anything that can live in a subdirectory out of root.

- `README.md` → `.github/README.md` (GitHub still renders it from `.github/` for repo landing page).
- `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, issue/PR templates → `.github/`.
- Tooling configs → dedicated dirs where the tool allows (`.config/`, `tools/`, language-native locations).
- Acceptable at root only: `LICENSE`, `.gitignore`, language manifest (`go.mod`, `package.json`, `pyproject.toml`, `pubspec.yaml`), `.editorconfig`, `.github/`.
- Sprawling root (>~8 visible entries) → propose move.

---

## 3. Linting — super-linter

[`super-linter`](https://github.com/super-linter/super-linter) is the **de-facto linter for all repos**. Run via GitHub Actions.

- Use **defaults** wherever possible. Override only with strong justification, documented in workflow comment.
- Single workflow: `.github/workflows/lint.yml` invoking `super-linter/super-linter@<sha>`.
- Per-language linter configs (`.eslintrc`, `.golangci.yml`, etc.) only when defaults genuinely don't fit.
- `super-linter` covers secret scanning — no separate `gitleaks`/`trufflehog` workflow.
- Avoid bespoke per-language lint workflows — consolidate under super-linter.

---

## 4. CI — paths-filter for Selective Jobs

Use [`dorny/paths-filter`](https://github.com/dorny/paths-filter) action to gate jobs on changed files. Apply to **every repo with multiple logical components** (backend/frontend, multiple services, docs vs code, etc.).

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
- One `changes` job, multiple filter outputs — one per logical component matching dir layout.
- Downstream jobs `needs: changes` + `if: needs.changes.outputs.<name> == 'true'`.
- Filter globs mirror repo's actual top-level component dirs.
- Saves CI minutes, faster feedback.

---

## 5. Workflow Hygiene — No Static Constants

**Never hardcode tags, versions, image names, or repeated strings in workflows.** Use template variables.

Rule: if a value is **already exposed** via GitHub context (`github.*`, `runner.*`, `secrets.*`, etc.), use the context expression **directly** — do not re-alias it through `env`. Only define `env` for values that have no upstream source (tool versions, custom config strings).

Bad — hardcoded:

```yaml
- uses: actions/setup-go@v5
  with:
    go-version: '1.23'
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
  GO_VERSION: '1.23'
jobs:
  build:
    steps:
      - uses: actions/setup-go@v5
        with:
          go-version: ${{ env.GO_VERSION }}
      - run: docker build -t ${{ github.repository }}:${{ github.sha }} .
```

- Pin action versions by SHA where possible.
- Reuse via `workflow_call` / composite actions when same logic repeats across repos.

---

## 6. Dependabot

**Required for every repo.** `.github/dependabot.yml` covering **all supported package ecosystems** present in the repo.

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
- **Body: very very concise.** One short paragraph max. Skip body if subject is self-explanatory. Skip "what" — diff shows it. Only "why" if non-obvious.
- One logical change per commit. No "misc fixes".
- PR title = top commit subject.
- Per-repo `commitlint` config aligned with above (suggest adding if missing).

---

## 8. Language Code Layout

Respect language-idiomatic layout. **Do not force uniform `src/` across all stacks.**

| Lang | Layout |
|------|--------|
| Go | [Standard Go Project Layout](https://github.com/golang-standards/project-layout): `cmd/`, `internal/`, `pkg/`, flat packages — no `src/` |
| TS/JS (lib) | `src/` + `dist/`, ESM, `package.json` `exports` field |
| TS/JS (Node app) | `src/`, `tests/`, build to `dist/` |
| Python | [src-layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/): `src/<pkg>/`, `tests/`, `pyproject.toml` |
| Dart/Flutter | `lib/`, `test/`, `assets/`, idiomatic Flutter structure |
| Rust | Cargo conventions: `src/`, `tests/`, `examples/` |

Tests live alongside or in idiomatic test dir per lang — pick one per repo, stay consistent.

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
- **Release flow**: tag creation triggers `push.yml` → release artifact published. Some repos may release on every push to `master` instead — detect from workflow.
- **No CHANGELOG file.** GitHub release notes auto-generated from commit history (Conventional Commits make this clean).

---

## 11. CI Workflow Naming

- **Primary push workflow**: `.github/workflows/push.yml`. One per repo. Triggered on push to `master` + tag creation.
- Other workflows kept narrow-purpose: `lint.yml` (super-linter), `dependabot-auto-merge.yml`, etc.
- Avoid generic `ci.yml` / `test.yml` — use `push.yml` as canonical entry.

---

## 12. README Convention

Repos use a **minimal README**. Detailed docs live elsewhere (external site, `docs/`, or upstream project).

Canonical template (root or `.github/`):

```markdown
# <RepoName> <a href="<docs-url-or-repo-url>"><img alt="documentation" align="left" src="<owner-avatar-url>"></a>

<one-line description OR "Documentation available at [<host>](<url>)." OR "Documentation not available yet.">
```

- Title-case repo name (Unicode OK).
- Anchor logo image links to docs site if exists, else upstream/repo URL.
- Body = single line. No install/usage/badges sections — those belong on docs site.
- If `docs/` folder exists locally, link to hosted version.

---

## 13. Pre-commit Hooks

**No local pre-commit framework.** Rely on CI (`super-linter` via `push.yml`) as single source of truth for lint/format enforcement. Don't suggest `pre-commit`/`husky`/`lefthook` setups.

---

## 14. Coverage & Testing

- **Target: 100% unit-test coverage.** Every PR should maintain or improve coverage.
- Coverage drop = blocker.
- Integration/e2e tests separate from unit coverage metric.

---

## 15. Dependency Policy

- **Always upgrade to latest** where compatible. Dependabot configured aggressively (weekly minimum, daily acceptable).
- Pin to exact versions when ecosystem allows; avoid range operators (`^`, `~`, `>=`) in production manifests.
- **Lockfiles not committed.** Add to `.gitignore`: `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `poetry.lock`, `uv.lock`, `Gemfile.lock`, `Cargo.lock` (binary projects only — libraries follow Rust convention). Go `go.sum` is exception (commit it — different semantics).

---

## 16. Definition of Done

A change is **done** only when all of:

1. Target behavior achieved (feature works / bug fixed).
2. Linted (super-linter clean).
3. Tested (coverage maintained at ~100% unit).
4. Docs updated (external site or in-repo `docs/` reflect change).

Don't mark complete or commit otherwise.

---

## 17. AI / Generator Attribution

**Do not attribute commits to AI.** No `Co-Authored-By: <bot>`, no `Generated with <tool>` trailers, no AI mentions in commit/PR bodies. Commits author = human only.

---

## 18. Naming Preferences

When naming new repos, services, packages, modules, or significant components, **prefer Ancient Latin** roots/words. Aim for short, evocative, semantically tied to function.

- Latin noun > Latin verb > English fallback.
- Avoid forced Latinizations of English terms — pick a real Latin word with fitting meaning instead.
- Single word preferred. Two-word combos only if one word doesn't capture intent.
- Propose 2–3 candidates with brief gloss (meaning + why it fits).

---

## 19. LICENSE

**GPL-3.0** universally. Every repo carries `LICENSE` at root with full GPL-3 text.

- New repos: add GPL-3 LICENSE at init.
- Drift: any repo missing LICENSE → add GPL-3.
- Exception: repos vendoring upstream code under incompatible license (e.g. forks of GPL-2-only or BSD projects) keep upstream license — preserve original `LICENSE`, add secondary license file (`LICENSE.<name>`) only if combining with new GPL-3 code.
- Rationale: aligns with copyleft-required deps and protects derivative works. All other transitive deps in current repos are permissive (MIT/BSD/Apache-2.0) and GPL-3-compatible.

---

## 20. Drift Detection Heuristics

When auditing repos, look for:

- `README.md` at root instead of `.github/README.md`.
- README longer than ~3 lines or with install/badges/usage sections (deviates from minimal template).
- Sprawling root dir — files belonging in `.github/`, `.config/`, or lang-idiomatic subdirs.
- Default branch ≠ `master`.
- Branch names not following `feat/` convention.
- Unsigned commits in recent history.
- Workflow file ≠ `push.yml` for primary CI.
- Missing `super-linter` workflow, or super-linter with non-default overrides lacking justification.
- CI workflows without `paths-filter` despite multi-component layout.
- Hardcoded versions/tags/image names in workflows, or `env` aliases re-aliasing exposed `${{ github.* }}` context.
- Missing `.github/dependabot.yml`, or dependabot missing ecosystems present in repo.
- Non-Conventional commit messages in recent history.
- Verbose commit bodies restating the diff.
- Lockfiles committed (except `go.sum`).
- Coverage <100% on unit tests.
- Presence of `CHANGELOG.md` (should not exist).
- Presence of `pre-commit`/`husky`/`lefthook` config (should not exist).
- AI co-author trailers in commit history (should not exist).
- Tag format ≠ `vX.Y.Z`.
- Inconsistent action pinning (mix of SHA vs tag vs major version).
- Missing or inconsistent `LICENSE` file across repos (expected: GPL-3 unless vendoring exception).
- Lang layout violations (e.g. Go repo with `src/`, Python repo flat-layout when src-layout expected).

Surface as **drift report**, not auto-fix.
