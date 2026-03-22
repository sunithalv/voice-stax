# Skill: Blog Author for Medium

Create a detailed, engaging Medium blog post from a VoiceStax project and optionally publish it directly to Medium.

## Workflow

1. **Read the project** — scan key files (README, core modules, examples) to understand the project deeply
2. **Generate the blog** — `python generate_blog.py <project_path> [--title <override>]`
3. **Review the output** — markdown file saved to `blog/output.md`
4. **Publish to Medium** — `python publish_medium.py <markdown_file> --token <token> [--publication-id <id>]`

---

## Step 1 — Generate Blog

```bash
python generate_blog.py <project_path> [--title "Custom Title"]
```

Reads the project at `<project_path>` and writes a structured Medium blog post to `blog/output.md`.

### What the generator extracts:
- README.md → project overview, features, tech stack
- pyproject.toml → dependencies, Python version
- Core modules → architecture decisions, design patterns
- Examples → usage code snippets
- WebSocket protocol → technical depth

### Blog structure:
```
Title
Subtitle
Tags: #python #voice-ai #pypi #open-source

[Opening hook — compelling problem statement]

## What is [ProjectName]?
[What it does, who it's for]

## Features
[Bulleted feature list from README + code snippets]

## Architecture
[How it works — pipeline diagram in text, component breakdown]

## Getting Started
[Installation + quick start code]

## Code Deep Dive
[Key architectural decisions with inline code snippets]

## WebSocket Protocol
[Technical reference — message types, flow]

## Why This Matters
[Problem solved, use cases, what's next]

## Conclusion
[Call to action — try it, contribute]
```

---

## Step 2 — Publish to Medium

```bash
python publish_medium.py <markdown_file> --token <integration_token> [--publication-id <id>]
```

### Medium Integration Token
Get yours at: `https://medium.com/me/settings/security`
→ Scroll to "Integration tokens" → Generate new token

Format: `xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`

### Publication vs Personal
- `--publication-id` omitted → posts to your personal Medium blog
- `--publication-id <id>` → posts to a Medium publication you contribute to

Finding a publication ID: open the publication page, the slug in the URL is the ID (e.g. `medium.com/@yourname/publishers/123456789` → ID is `123456789`)

### What it does:
1. Converts markdown to HTML (handles code blocks, bold, italic, headers, lists)
2. Creates a Medium post via `POST https://api.medium.com/v1/posts`
3. Returns the published URL

---

## Requirements (Python deps)

```bash
pip install requests python-dotenv markdown
```

---

## Notes

- The generator uses the project structure to auto-detect content — no manual input needed beyond the path
- For the best blog, ensure README.md is well-filled (VoiceStax already is ✅)
- Medium's API has rate limits; don't spam publishes
- Integration tokens work for posting to your own Medium account only
