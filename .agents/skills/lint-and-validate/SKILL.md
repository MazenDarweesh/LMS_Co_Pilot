---
name: lint-and-validate
description: >
  Performs automated linting, type checking, and static analysis on Python
  files in Antigravity. Activates for tasks like "lint", "check", "validate",
  "review PR", or "fix typing".
---

# Lint and Validate Skill

You are an automated linter and static analyzer operating in the Antigravity environment.

## Execution Steps:

1. **Load Project Rules:**
   - Read `.agents/rules/python-typing.md` and `.agents/rules/async-safety.md`.
   - If `service-pattern.md` exists, load it for concurrency rules.

2. **Analyze Code:**
   - **Syntax:** Check for indentation and syntax errors using AST parsing.
   - **Type Hints:** Enforce `mypy` strict mode standards (use `|` instead of `Union`).
   - **Imports:** Flag unused imports and ensure `isort` order (standard library → third-party → local).
   - **Async Safety:** Verify all blocking I/O uses `asyncio.to_thread` (for sync libs) or native async.

3. **Automated Tools (If Available):**
   - Run `mypy --strict <file>` and `ruff check <file>`.
   - If tools are missing, perform manual checks based on the project rules.

## Output Format:

Produce a structured Markdown report:

```markdown
# 🧹 Lint Report — `filename.py`
## Summary
| Check | Status | Details |
|-------|--------|---------|
| Syntax | ✅ | No errors |
| Type Hints | ❌ | Missing return type in `get_user()` |
| Imports | ⚠️ | 2 unused imports (`os`, `json`) |
| Async Safety | ✅ | All blocking ops wrapped in `to_thread` |

## Detailed Errors
| File | Line | Issue | Suggested Fix |
|------|------|-------|---------------|
| auth_service.py | 45 | Missing `Optional` | `user: dict[str, Any] \| None` |

---

✅ **Final Verdict:** PASS / FAIL