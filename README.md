# roadmap-tutor

[![skills.sh](https://skills.sh/b/instax-dutta/roadmap-tutor)](https://skills.sh/instax-dutta/roadmap-tutor)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A [Hermes Agent](https://github.com/NousResearch/hermes-agent) skill that turns
any of the 91 official [roadmap.sh](https://roadmap.sh) roadmaps into a
resumable, one-topic-at-a-time curriculum.

Ask your agent to "continue" and it teaches you the next node of your roadmap —
one concept, the curated resources, and your progress. Then it remembers where
you stopped.

Built for the ten-minute gap between classes.

```
You:  continue
Bot:  ACID — More about Databases                        69/155 · 7.7%

      Four guarantees a database makes about a transaction. Atomicity means
      all-or-nothing: a half-applied transfer never exists. Consistency keeps
      every constraint true before and after. Isolation stops concurrent
      transactions from seeing each other's partial work. Durability means a
      commit survives the power going out.

      Worth 8 minutes: "ACID Explained" (video)
      Say "done" when it's landed, or "skip" if you've got it already.
```

## Why

Learning happens in the gaps — between classes, on a commute, waiting for a
build. Those gaps are too short to open a course and too frequent to waste.
This skill makes the unit of learning exactly one flowchart node, and makes the
state survive across days, devices, and chat platforms.

Because Hermes speaks Discord, Telegram, WhatsApp, Slack, SMS and email, the
same curriculum follows you to whichever one is already open on your phone.

## Install

Hermes Agent:

```bash
hermes skills install instax-dutta/roadmap-tutor
```

Any other skills-compatible agent (Claude Code, Cursor, Codex, OpenCode,
Goose, Windsurf, …):

```bash
npx skills add instax-dutta/roadmap-tutor
```

Or clone it straight into your skills directory:

```bash
git clone https://github.com/instax-dutta/roadmap-tutor \
  ~/.hermes/skills/roadmap-tutor
```

There is nothing else to do. No `pip install`, no API key, no config file, no
background process.

Verify:

```bash
python3 ~/.hermes/skills/roadmap-tutor/scripts/roadmap.py list backend
```

## Usage

Talk to your agent normally:

| You say | What happens |
|---|---|
| "start the backend roadmap" | Begins tracking, 155 steps queued |
| "continue" / "next" | Teaches the next unfinished node |
| "done" | Marks it complete, advances |
| "skip" — "I already know Redis" | Skips without inflating your percentage |
| "where am I?" | Progress across every roadmap you're tracking |
| "show me the whole roadmap" | Numbered checklist with completion marks |
| "jump to Docker" | Moves the cursor to that node |
| "switch to the python roadmap" | Changes the active track |

Multiple roadmaps can be in flight at once.

## Direct CLI

The skill is a thin wrapper over one script, usable on its own:

```bash
python3 scripts/roadmap.py start backend
python3 scripts/roadmap.py next --brief
python3 scripts/roadmap.py done --note "revise before interviews"
python3 scripts/roadmap.py status
python3 scripts/roadmap.py outline | less
```

Run `python3 scripts/roadmap.py --help` for the full surface.

## Running on a Raspberry Pi

This was written for a Pi 4 with 2 GB of RAM, and it is deliberately boring:

- **Standard library only.** No numpy, no requests, no lxml.
- **~40 MB peak RSS**, sub-second warm responses.
- **No daemon.** The script runs, prints JSON, exits.
- **Aggressive caching.** Roadmap graphs and topic write-ups are cached for 14
  days under `roadmap-tutor/cache/` (a full roadmap is a few hundred KB).

Warm the cache before you leave Wi-Fi:

```bash
python3 scripts/roadmap.py prefetch --count 30
```

After that, `next` works entirely offline.

## How it works

`roadmap.sh/<slug>.json` is a [reactflow](https://reactflow.dev) graph, not an
ordered syllabus — nodes carry x/y coordinates and edges are drawn between some
but not all of them. Reading it top to bottom gives you nonsense.

`scripts/roadmap.py` flattens it properly:

1. **Topic order** comes from a topological sort over topic-to-topic edges,
   with layout position breaking ties and reconnecting disjoint components.
2. **Subtopics attach to topics** via three signals in descending trust — an
   explicit edge, shared membership in a `section` box, then nearest-topic by
   edge-to-edge box distance weighted to prefer the heading directly above.
3. **Section captions** (floating `label` nodes like "Hashing Algorithms") are
   matched to their boxes and surfaced as the `group` field.
4. **Orphans are recovered** at the end so no node is ever silently dropped.

Validated against all 91 official roadmaps: every learnable node appears
exactly once, no duplicates, no losses.

Per-node write-ups and their curated resources come from
`roadmap.sh/api/v1-official-roadmap-topic/<slug>/<nodeId>`.

## State

Progress is a single JSON file at `$HERMES_HOME/roadmap-tutor/state.json`,
overridable with `ROADMAP_TUTOR_HOME`:

```json
{
  "active": "backend",
  "roadmaps": {
    "backend": {
      "cursor": 68,
      "done": ["SiYUdtYMDImRPmV2_XPkH"],
      "skipped": [],
      "notes": {"qSAdfaGUfn8mtmDjHJi3z": "revise before interviews"}
    }
  }
}
```

Writes are atomic, so a power cut mid-update can't corrupt it. Back it up by
copying the file.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `ROADMAP_TUTOR_HOME` | `$HERMES_HOME/roadmap-tutor` | State and cache location |
| `ROADMAP_TUTOR_TTL` | `1209600` (14 days) | Cache lifetime in seconds |

## Daily nudge

```bash
hermes cron create --name roadmap-nudge --schedule "0 9 * * *" \
  --skill roadmap-tutor \
  --prompt "Run the roadmap-tutor next command and teach me one topic."
```

## Credits

Roadmap content belongs to [roadmap.sh](https://roadmap.sh) and its
[contributors](https://github.com/kamranahmedse/developer-roadmap), and is
fetched live from their public endpoints. This skill only sequences and tracks
it.
