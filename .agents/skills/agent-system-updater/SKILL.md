---
name: agent-system-updater
description: >
  Reviews session history to detect drift in existing skills and rules.
  Proposes targeted diff-style updates when a skill produced wrong output,
  a rule was manually overridden, or an instruction had to be repeated.
  Writes proposals to .agents/proposals/ and waits for approval before editing.
---

# Agent System Updater Skill

You are the self-maintenance engine for the LMS Co-Pilot agent system.
Your job is to detect when existing skills or rules are no longer accurate
and propose precise updates — but NEVER apply them without user approval.

## When to Activate

This skill should run at the END of any session where any of these occurred:
- The agent gave wrong output after a skill was activated
- The user had to re-explain a constraint that should already be in a rule
- A `# type: ignore` was added, a checklist item was missed, or a pattern was violated
- The user corrected the agent's behavior more than once for the same reason

## Step 1: Scan for Drift Signals

Review what happened in this session. Look for:

| Signal | Affected Component |
|:-------|:------------------|
| Agent used `Optional[X]` despite python-typing.md rule | `rules/python-typing.md` |
| Agent wrote blocking call in async function | `rules/async-safety.md` |
| Agent forgot `initialize()` pattern for new service | `rules/service-pattern.md` |
| RAG debug output missed a field or wrong threshold | `skills/rag-debug-analyst/SKILL.md` |
| Linter checklist was incomplete | `skills/search-pipeline-linter/SKILL.md` |
| Commit message used wrong format/scope | `skills/commit-message-generator/SKILL.md` |
| Service template needed changing | `skills/service-bootstrapper/templates/` |

## Step 2: Read the Current File

Use `view_file` to read the exact current content of the affected file.
Never propose changes based on memory alone.

## Step 3: Write the Proposal File

Write to: `.agents/proposals/update_YYYYMMDD_HHMMSS.md`

Use this exact format:

```markdown
# Agent System Update Proposal — [DATE]

## Detected Drift
- **Session Evidence:** [Describe what went wrong — be specific]
- **Affected File:** `.agents/[path/to/file.md]`
- **Root Cause:** [Why did this drift happen?]

## Proposed Change

### Current Content (relevant excerpt):
```
[paste the current lines]
```

### Proposed Replacement:
```
[paste the new lines]
```

### Diff Summary:
```diff
- [old line]
+ [new line]
```

## Impact Assessment
- Will this change affect behavior for future sessions? [Yes/No + explanation]
- Could this break existing patterns? [Yes/No + explanation]

## Awaiting Approval
Reply:
- "apply" → I will make the change to the actual file
- "reject" → discard this proposal
- "modify: [your changes]" → I will revise the proposal
```

## Step 4: STOP and Wait

After writing the proposal file:
1. Tell the user: "I've written an update proposal to `.agents/proposals/update_[DATE].md`. Please review and reply 'apply' or 'reject'."
2. Do NOT touch any `.agents/skills/` or `.agents/rules/` files until approved.

## After Approval

When the user says "apply":
1. Use `view_file` to read the current file one more time (defensive recon)
2. Use `replace_file_content` for single-block changes or `multi_replace_file_content` for multiple
3. Confirm: "Update applied ✅ — [filename] has been updated."

## Slash Command

`/agent-system-updater`
