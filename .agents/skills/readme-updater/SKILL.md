---
name: readme-updater
description: >
  Updates README.md to be a professional, market-ready project showcase after every commit.
  Use when the user commits code, adds a new endpoint, or wants the README to reflect
  the current project state for job applications, GitHub portfolio, or team onboarding.
---

# README Updater Skill

You are a technical writer and AI/ML portfolio specialist.
When activated, update `README.md` to accurately reflect the current project state
while maintaining a professional, market-ready format for the AI engineering job market.

## When to Activate

- After every `git commit` (triggered by hook)
- When the user says "update README", "refresh the docs", "portfolio ready?"
- When a new endpoint, service, or major feature is added

## Step 1: Detect What Changed

Read these files to understand current state:
1. `src/api/v1/router.py` — extract all `@router.get/post/delete` endpoints
2. `src/services/` — list all service files to detect new capabilities
3. `src/models/` — detect new request/response schemas
4. Latest file in `downloads/search_debugs/` — extract real latency numbers for metrics section
5. `pyproject.toml` — detect dependencies for tech stack section

## Step 2: Identify Changed Sections

Only update sections that are actually stale. The README has these sections:

| Section | When to Update |
|:--------|:---------------|
| `## API Endpoints` | New endpoint added or removed |
| `## Performance Metrics` | New trace file with better/worse numbers |
| `## Features` | New capability implemented |
| `## Roadmap` | Completed item should be checked off |
| `## Tech Stack` | New dependency added |

**NEVER change:** the project header, badges, architecture diagram, or author section
unless the user explicitly asks.

## Step 3: Rewrite Stale Sections

Follow the README template below exactly. Use real data extracted from the codebase.

## README Template — Maintain This Structure

```markdown
# 🎓 LMS AI Co-Pilot

[badges row]

> One-line elevator pitch

## ✨ Key Features
[bullet list]

## 🏗️ Architecture
[ASCII/mermaid diagram]

## 🚀 API Endpoints
[table]

## 📊 Performance
[metrics table from latest trace]

## 🛠️ Tech Stack
[table]

## ⚡ Quick Start
[3-command setup]

## 🗺️ Roadmap
[checklist]

## 👨‍💻 Author
[contact]
```

## Quality Rules for Market-Ready README

- ✅ Write in English (international market)
- ✅ Lead with VALUE not implementation: "powers context-aware Q&A" not "uses Qdrant"
- ✅ Use concrete numbers: "< 35s end-to-end" not "fast response"
- ✅ Badges must be real (shields.io) and reflect actual versions
- ✅ Architecture diagram must be accurate to the CURRENT codebase
- ❌ No placeholder text like "coming soon" or "TODO"
- ❌ No Arabic text in README (GitHub international audience)
- ❌ No internal file paths visible to the reader

## Slash Command

`/readme-updater`
