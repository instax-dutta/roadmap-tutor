---
name: roadmap-tutor
description: Learn a roadmap.sh developer roadmap one topic at a time, with progress tracked across sessions. Use when the user says "continue", "next topic", "teach me the next bit", "what's next on my roadmap", "start the backend/python/devops roadmap", "where am I", "mark that done", or asks to learn a skill in short bursts. Built for micro-learning in 10-minute gaps — one flowchart node per turn, resumable from any chat platform, and light enough to run on a Raspberry Pi.
license: MIT
compatibility: Requires python3 (3.7+, standard library only) and outbound HTTPS to roadmap.sh on first use. Cached topics work offline afterwards. Runs on a Raspberry Pi in ~40MB RAM.
metadata:
  author: instax-dutta
  version: "1.0.0"
  homepage: https://github.com/instax-dutta/roadmap-tutor
---

# roadmap.sh Tutor

Turns any of the 91 official [roadmap.sh](https://roadmap.sh) roadmaps into a
resumable, one-topic-at-a-time curriculum. The flowchart is flattened into a
linear order, the user's position is persisted to disk, and each turn delivers
exactly one node — the write-up, the curated resources, and where it sits in
the bigger picture.

Designed for the ten-minute gap between classes: the user says "continue", gets
one concept, and the cursor moves.

## When to Use

- "continue" / "next" / "next topic" / "kal se aage" — the core loop
- "start the backend roadmap" / "switch to devops"
- "where am I?" / "how much is left?" / "show my progress"
- "mark that done" / "skip this one" / "I already know Redis"
- "show me the whole roadmap" / "jump to Docker"
- Any request to learn a technical subject in small, tracked increments

Do NOT use this for one-off factual questions ("what is a mutex?"). That's a
normal answer, not a curriculum step.

## The Script

Everything runs through one stdlib-only Python file. No pip, no daemon.

```bash
python3 scripts/roadmap.py <command> [args]
```

Every command prints JSON (except `outline`, which prints a checklist). Parse
the JSON, then **teach from it in your own words** — never paste raw JSON at
the user.

| Command | What it does |
|---|---|
| `list [query]` | All 91 roadmap slugs, optionally filtered |
| `start <slug>` | Begin tracking a roadmap and make it active |
| `next` | The next unfinished step + content + resources |
| `current` | Re-show the current step without advancing |
| `done [id\|title] [--note "..."]` | Mark complete, advance the cursor |
| `skip` | Skip the current step, advance the cursor |
| `status` | Progress across every tracked roadmap |
| `outline` | Full numbered checklist with `[x]` / `[~]` marks |
| `search <query>` | Find a step by title |
| `goto <n\|id\|title>` | Jump the cursor to a specific step |
| `switch <slug>` | Change which roadmap is active |
| `prefetch --count N` | Warm the offline cache for the next N steps |
| `reset` | Wipe progress for one roadmap |

Add `--slug <name>` to any command to target a non-active roadmap.
Add `--brief` to `next` / `current` / `goto` for just the opening paragraph.

## The Core Loop

When the user says "continue" or anything equivalent:

1. Run `next`.
2. Read `title`, `section`, `content`, `resources`, `progress` from the JSON.
3. Teach it: explain the concept in 3-6 sentences, in your own voice, at the
   level implied by the roadmap's position. Ground it in `content` — do not
   invent facts that contradict it.
4. Offer 1-2 of the best `resources` as follow-up reading, with the type
   (`@article@`, `@video@`, `@official@`) made human ("a short video", "the
   official docs").
5. Close with the progress line: `12/155 · 7.7%` and the natural next action.

Do **not** call `done` automatically. Advancing is the user's decision — they
may want to sit with a topic. Call `done` only when they signal completion
("got it", "done", "next"). If they say "next" without confirming
understanding, treat that as `done` + `next` in one turn.

### Example turn

User: *continue*

```bash
python3 scripts/roadmap.py next
```

```json
{
  "roadmap": "backend",
  "position": "69/155",
  "title": "ACID",
  "kind": "subtopic",
  "section": "More about Databases",
  "content": "# ACID\n\nACID represents four database transaction properties...",
  "resources": [
    {"type": "video", "title": "ACID Explained", "url": "https://youtube.com/..."}
  ],
  "progress": {"total": 155, "done": 12, "percent": 7.7}
}
```

You then explain ACID conversationally, tie it back to *More about Databases*,
point at the video, and end with `69/155 · 7.7% — say "done" when you've got it.`

## Behaviour Rules

1. **One node per turn.** Never batch three topics because they look small.
   The entire value of this skill is the small dose. If the user explicitly
   asks for more ("give me the next 3"), that's the one exception.
2. **Teach, don't dump.** `content` is raw markdown from roadmap.sh, often
   terse and sometimes just a heading. Expand it. If `content` says
   "(No write-up on roadmap.sh for this node)", explain the topic yourself
   from the title and section — do not tell the user the node is empty.
3. **Respect the gap.** Default to something readable in under three minutes.
   Match the user's evident time budget if they mention one.
4. **Progress goes in every reply.** `12/155 · 7.7%` — it's the motivation.
5. **Never fabricate resource links.** Only surface URLs present in
   `resources`. If the array is empty, say so or point at the roadmap page.
6. **Persist immediately.** Every `done` / `skip` / `goto` writes to disk, so
   the user can close the chat mid-topic and resume days later from a
   different platform.

## Picking a Roadmap

If the user names a roadmap that isn't an exact slug, resolve it first:

```bash
python3 scripts/roadmap.py list backend
```

Then `start` the match. If several match ("java" → `java`, `javascript`), ask
which one rather than guessing. `backend-beginner`, `frontend-beginner`,
`devops-beginner`, and `git-github-beginner` exist as gentler variants — offer
those if the user says they're new.

## State

Progress lives at `$HERMES_HOME/roadmap-tutor/state.json`
(override with `ROADMAP_TUTOR_HOME`):

```json
{
  "active": "backend",
  "roadmaps": {
    "backend": {
      "cursor": 68,
      "done": ["SiYUdtYMDImRPmV2_XPkH", "..."],
      "skipped": [],
      "notes": {"qSAdfaGUfn8mtmDjHJi3z": "revise before interviews"}
    }
  }
}
```

Multiple roadmaps can be tracked at once; `active` decides the default. Notes
attached via `done --note` are the user's own words — surface them if they
revisit that step.

## Offline & Low-Memory Notes

- Roadmap graphs and topic write-ups are cached under
  `roadmap-tutor/cache/` for 14 days (`ROADMAP_TUTOR_TTL` in seconds).
- Once cached, `next` works with no network. Run
  `prefetch --count 30` on Wi-Fi to load up a session's worth ahead of time.
- Peak memory is ~40 MB and a warm call returns in well under a second, so it
  runs comfortably on a Raspberry Pi 4 with 2 GB RAM.
- Stdlib only — nothing to `pip install`, nothing to keep running.

## Pitfalls

1. **Don't shell out to `curl` against roadmap.sh yourself.** The flattening
   logic (edge ordering, section grouping, orphan recovery) lives in the
   script. Raw JSON from `roadmap.sh/<slug>.json` is a reactflow graph, not a
   list, and reading it in order will give the user nonsense.
2. **`done` with no argument marks the *current cursor*, not the last thing
   discussed.** If the conversation drifted, pass the title explicitly:
   `done "ACID"`.
3. **`skip` is not `done`.** Skipped steps stay out of the completion
   percentage — that's deliberate, so "I already know this" doesn't inflate
   real progress.
4. **The cursor advances past the end.** When `next` returns
   `"status": "complete"`, congratulate the user and offer a related roadmap
   rather than looping.
5. **A first call on a cold cache hits the network twice** (graph + topic).
   On a slow Pi connection that's a couple of seconds — don't retry, just wait.
6. **Content can legitimately be empty.** Some flowchart nodes are headings
   with no write-up. Teach from the title; never surface the placeholder text
   verbatim.

## Install

```bash
hermes skills install instax-dutta/roadmap-tutor
```

Or manually:

```bash
git clone https://github.com/instax-dutta/roadmap-tutor \
  ~/.hermes/skills/roadmap-tutor
```

No dependencies, no auth, no configuration. Verify with:

```bash
python3 ~/.hermes/skills/roadmap-tutor/scripts/roadmap.py list backend
```

## Cron Companion (optional)

A daily nudge, using the gateway rather than the agent loop:

```bash
hermes cron create --name roadmap-nudge --schedule "0 9 * * *" \
  --skill roadmap-tutor \
  --prompt "Run the roadmap-tutor next command and teach me one topic."
```
