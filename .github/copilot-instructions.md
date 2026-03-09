---
applyTo: '**'
description: 'Bitvavo trading bot - autonomous AI assistant instructions'
---

# Bitvavo Bot - Copilot Instructions

## Core Rules (Highest Priority)
- ALWAYS follow `docs/AUTONOMOUS_EXECUTION_PROMPT.md` verbatim (absolute highest priority)
- NO questions - decide autonomously, execute, verify, complete
- Verify: `get_errors()` + run tests before marking "done"
- Compact output: max 5-10 lines
- Bot restart: `start_automated.bat` only
- Backup critical files before edit

**This is a ZERO-QUESTION workspace.**  
**Prompt Version:** 3.0 | **Strictness:** MAXIMUM | **Autonomy Level:** FULL | **Verification:** MANDATORY

---

## Surgical Code Modification
- **Preserve Existing Code**: The codebase is the source of truth - respect its structure, style, and logic.
- **Minimal Necessary Changes**: Alter the absolute minimum amount of existing code required.
- **Explicit Instructions Only**: Only modify code explicitly targeted by the request. No unsolicited refactoring.
- **Integrate, Don't Replace**: Add logic into existing structure rather than replacing entire blocks.

## Code Generation (Python)
- Simplest solution possible - no over-engineering, no premature optimization.
- Favor standard library; only introduce third-party packages if absolutely necessary.
- Follow **PEP 8**: 4-space indent, max 79 chars per line, blank lines between functions/classes.
- Use type hints and descriptive function names.
- Write docstrings (PEP 257) for all functions; include comments explaining *why* decisions were made.
- Handle edge cases explicitly with clear exception handling.
- Use `lru_cache` for expensive repeated computations (price lookups, indicator calc).
- Use `asyncio` for I/O-bound operations; avoid blocking the event loop.
- Profile with `cProfile` or `Py-Spy` before optimizing - measure first.
- Use built-in data structures (`dict`, `set`, `deque`) over custom implementations.

## Security (Critical - Bot handles real money & API keys)
- **Never hardcode secrets**: API keys, tokens, passwords MUST come from environment variables or config files excluded from git.
- **No raw credentials in code**: If a secret appears in generated code, replace with `os.environ['KEY_NAME']` and add a comment.
- **Sanitize all external inputs**: Validate data from API responses before using in calculations or order logic.
- **Parameterized queries only**: No string concatenation for any database or file queries.
- **Fail closed**: On ambiguous or errored security/governance checks, deny the action rather than allowing it.
- **Least privilege**: Each module/function gets only the access it needs - no blanket permissions.
- **Use strong algorithms only**: Never use MD5/SHA-1 for sensitive data; use AES-256 or Argon2/bcrypt.
- **Protect data in transit**: Always use HTTPS for external API calls; never downgrade to HTTP.
- **Scan arguments before execution**: Filter generated order arguments for anomalies — API keys, negative amounts, zero prices, extreme deviations.
- **Dependency hygiene**: Run `pip-audit` regularly; flag known-vulnerable packages before installing.

## Bot Safety (Autonomous trading - high impact actions)
- **Audit all order actions**: Every trade, cancel, and DCA trigger must be logged with timestamp, market, amount, reason.
- **Rate limit guards**: Enforce max API calls per interval; never allow unbounded loops over exchange calls.
- **Human-in-the-loop for destructive actions**: Sell-all, cancel-all, config resets require explicit confirmation or are flagged in logs.
- **Append-only audit logs**: Never modify or delete existing audit trail entries - immutability enables debugging.
- **Scan generated arguments**: Before passing values to order functions, validate for anomalies (negative amounts, zero prices, extreme deviations).
- **No self-modification of governance**: Code must not modify its own safety limits, stop-loss thresholds, or audit config at runtime without explicit user action.
- **Explicit tool allowlist**: Each module accesses only the API endpoints it needs — no blanket permissions across modules.
- **Content scanning**: Scan all external data (API responses, config files) for injection patterns before use in logic.
- **Audit log format**: Export audit entries as JSON Lines (one JSON object per line) for log aggregation compatibility.
- **Policy as config**: Governance rules (score thresholds, max order sizes, stop-loss limits) live in config files, not hardcoded in logic.
- **Log decisions, not secrets**: Audit logs must record decisions and metadata — never log raw API keys, credentials, or user tokens.

## Tool Usage
- Use tools when necessary for accurate, factual answers - do not avoid them.
- Apply changes directly to the codebase; never generate copy-paste snippets when direct edit is possible.
- Every tool action must be a necessary step toward the stated goal.

## Interaction Style
- Direct and concise - no filler, no verbose explanations.
- Use natural language by default; only provide code blocks when explicitly asked or essential.
- Explain the *why* briefly: reasoning > solution alone.
