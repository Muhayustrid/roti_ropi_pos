# CLAUDE.md

Claude Code entry point for this repository. This file points to the canonical rules; it does not
restate them.

## Read first

1. `AGENTS.md` — project-wide workflow, ownership boundaries, permissions, API and testing rules.
   It is authoritative and overrides skills.
2. `PROJECT_STATE.md` — the resume checkpoint. Read it when starting or resuming project work, before
   touching code. It names the active task, verified state, blockers, and the exact next action.

Git, executable tests, and the live site override both files. When `PROJECT_STATE.md` disagrees with
verified evidence, correct the file rather than working around it.

## Navigation

`.codegraph/` exists, so use `codegraph_explore` as the first navigation step — one call returns
verbatim line-numbered source plus call paths and blast radius. Fall back to direct Read/Grep when you
need exact implementation detail, when the index looks stale, or when the symbol is not indexed.
Installed Frappe and ERPNext source remains authoritative for framework behaviour; never infer
correctness from CodeGraph output alone.

## Subagents

Give a subagent its task brief plus the relevant slice of the current checkpoint. Never paste
accumulated session history, and never make a subagent rediscover the repository. Model tiers:
Haiku/Sonnet for exploration and implementation, Opus for reviewer roles only.

## Checkpoint discipline

Update `PROJECT_STATE.md` at meaningful task or phase boundaries and before handing work to a fresh
session: replace obsolete current-state text, record verification and blockers, and name the next task.
Skip it for trivial edits.

## Verification

Do not claim completion without fresh command output and a review of the intended diff. Run tests
inside `/workspace/development/frappe-bench` in the `frappe_docker_devcontainer-frappe-1` container.
Never run two suites concurrently against one site. Commit, push, migrate, and deploy each require
explicit user approval per `AGENTS.md`.
