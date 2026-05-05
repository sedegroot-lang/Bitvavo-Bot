# `.github/` — Copilot customization for the Bitvavo bot

This directory bundles all GitHub Copilot customizations for the project.

## Layout

| File / Folder | Purpose | Auto-loaded? |
|---|---|---|
| `copilot-instructions.md` | Repo-wide instructions (always on for Copilot in VS Code) | ✅ always |
| `instructions/*.instructions.md` | Path-scoped guidance via `applyTo:` glob in front-matter | ✅ when matched |
| `prompts/*.prompt.md` | Slash-commands you invoke explicitly (`/health`, `/fix`, `/reconcile`, …) | invoked |
| `agents/*.agent.md` | Specialised chat modes (`bug-fix`, `config-tuner`, `code-review`) | selected |
| `skills/<name>/SKILL.md` | Reusable workflow recipes (`deploy-fix`, `investigate-desync`) | invoked |
| `hooks/*.md` | Post-action guidance (e.g. `post-edit-py`) | event-driven |

## Companion files outside `.github/`

| File | Role |
|---|---|
| `../AGENTS.md` | Cross-tool agent guidance (Copilot CLI, Cursor, Codex) |
| `../.vscode/mcp.json` | Workspace MCP servers (filesystem, git, sequential-thinking) |

## Quick reference — slash commands

| Command | What it does |
|---|---|
| `/health` | Run `ai_health_check.py` and summarise |
| `/fix` | Disciplined bug-fix flow (FIX_LOG → fix → test → log → push → telegram → restart) |
| `/reconcile <market>` | Stop bot, reconcile from order history, restart |
| `/config-set KEY=VALUE` | Edit ONLY the LOCAL override file with budget+roadmap check |
| `/restart-bot` | Stop+restart trailing_bot.py |
| `/telegram <message>` | Send via configured TELEGRAM_BOT_TOKEN/CHAT_ID |

## Quick reference — agents (chat mode picker)

| Agent | When to use |
|---|---|
| `bug-fix` | Any bug fix — enforces FIX_LOG workflow |
| `config-tuner` | Changing any config value — only LOCAL file, budget-aware |
| `code-review` | Read-only review of changes against project conventions |

## Quick reference — skills

| Skill | Trigger |
|---|---|
| `deploy-fix` | After a bug fix code change is in place |
| `investigate-desync` | A market's bot state ≠ exchange reality |

## Maintenance rules

1. Keep `copilot-instructions.md` reasonably short — push deep detail into `instructions/*.instructions.md` with `applyTo:`.
2. Path-scoped instructions only load when files matching `applyTo:` are touched — favour them for noisy, language- or area-specific rules.
3. Prompt files should be **task-specific** with concrete steps; agents are **persistent personas** with tool restrictions.
4. Skills are **resource bundles** (markdown + optional scripts); use them when a workflow needs to be reused across many conversations.
5. After updating any file here, no restart is needed — VS Code Copilot picks up changes on the next interaction.
