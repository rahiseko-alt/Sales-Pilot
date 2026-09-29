# AGENTS.md

## Agent skills

Skills come from [mattpocock/skills](https://github.com/mattpocock/skills), installed into `.claude/skills/` with `npx skills add mattpocock/skills` and pinned in `skills-lock.json`. Do not edit them locally; update with `npx skills update`.

### Issue tracker

Issues and specs live as GitHub issues in this repo, via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context: `CONTEXT.md` at the repo root, ADRs in `docs/adr/`. Both are created lazily by `domain-modeling`. See `docs/agents/domain.md`.

## Navigation (repo-local)

This repo may be driven by a non-engineer. Never assume the user knows which slash command to run.

- The `next-step` skill (`.claude/skills/next-step/`, repo-local, not from mattpocock/skills) diagnoses where the work currently stands and proposes exactly one command to run next.
- A `SessionStart` hook in `.claude/settings.json` loads `docs/agents/flow-map.md` into context at the start of every session.
- Before writing implementation code for a request that has not been through the flow, run `next-step` first. Skip it only if the user explicitly says to go straight to code.
- Session ceremonies: `s` reports where the last session left off (run it at the top of the first reply of every session, unprompted); `f` drives the repo to a state where the container can be destroyed safely and then declares, with evidence, whether it is safe to close. Both are repo-local skills, triggered by the bare letter or the slash command.
- `docs/agents/handover.md` carries state across sessions: the container is ephemeral, so anything not written there is lost. Append a new entry at the top when work is shipped or a direction is agreed, run `.claude/hooks/handover-trim.sh`, and commit it immediately. `.claude/hooks/session-start.sh` owns the retention and read-window numbers; don't restate them elsewhere.

## Development flow

### Starting new work, or adding a feature to an existing codebase

`/grill-with-docs` -> `/to-spec` (when a spec is warranted) -> `/to-tickets` -> `/implement`

`/grill-with-docs` is the single entry point, whether or not code exists yet. It drives both `/grilling` and
`/domain-modeling`, so the vocabulary and the decisions land in `CONTEXT.md` and `docs/adr/` instead of
evaporating with the session. Those files are created lazily, so there is nothing to write and nothing to skip
when a repo is still empty. `/grill-me` is installed but deliberately unused: it runs `/grilling` alone, so it
records nothing.

`/implement` drives `/tdd` at pre-agreed seams: red -> green, one behaviour at a time, tested through the public interface rather than implementation details, one vertical slice per loop. It closes with `/code-review` before committing.

### Before a large feature, when code is hard to test, or when structure has grown complex

`/improve-codebase-architecture` -> pick a candidate -> `/grill-with-docs` or `/codebase-design` -> `/to-spec` -> `/to-tickets` -> `/implement`

`/improve-codebase-architecture` is a survey: it explores the codebase and hands back candidates. It never rewrites code on its own. Only the candidate the user picks goes through the flow above.
