# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

**This binds regardless of how the work started.** The skills below (`to-spec`, `to-tickets`, `tdd`,
`improve-codebase-architecture`) already read `CONTEXT.md`/`docs/adr/` because their own instructions say so.
But `docs/agents/flow-map.md` lets the user skip the flow entirely ("そのまま作って") and write code directly —
and when that happens, none of those skills run, so nothing else prompts this read. `flow-map.md` carries a
rule pointing back here for exactly that case: before writing code outside the flow, read this page's
"Before exploring, read these" section yourself. Skipping the flow must not also mean skipping this.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root, or
- **`CONTEXT-MAP.md`** at the repo root if it exists: it points at one `CONTEXT.md` per context. Read each one relevant to the topic.
- **`docs/adr/`**: read ADRs that touch the area you're about to work in. In multi-context repos, also check `src/<context>/docs/adr/` for context-scoped decisions.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates them lazily when terms or decisions actually get resolved.

## File structure

Single-context repo (most repos):

```
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-event-sourced-orders.md
│   └── 0002-postgres-for-write-model.md
└── src/
```

Multi-context repo (presence of `CONTEXT-MAP.md` at the root):

```
/
├── CONTEXT-MAP.md
├── docs/adr/                          ← system-wide decisions
└── src/
    ├── ordering/
    │   ├── CONTEXT.md
    │   └── docs/adr/                  ← context-specific decisions
    └── billing/
        ├── CONTEXT.md
        └── docs/adr/
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0007 (event-sourced orders), but worth reopening because…_

## Feed `/code-review`'s Standards axis

`/code-review` (vendored, not editable here) only searches for `CODING_STANDARDS.md`/`CONTRIBUTING.md`-style
files when building its Standards sub-agent prompt. It never looks at `CONTEXT.md` or `docs/adr/` on its own,
and that sub-agent runs isolated — it only sees what got pasted into its prompt. Left alone, an ADR is never
checked at the one step that reviews a diff before it ships.

Before spawning code-review's Standards sub-agent, the orchestrating agent must:

1. List the ADRs under `docs/adr/` (and `src/<context>/docs/adr/` in multi-context repos) that touch the
   area the diff changes.
2. Paste their contents into the Standards sub-agent prompt alongside whatever `CODING_STANDARDS.md`-style
   files code-review already found, with the instruction: a diff that contradicts a pasted ADR is a hard
   violation — cite the ADR number, not just "judgement call".
