#!/usr/bin/env python3
"""roadmap.sh learning tracker - single-file, stdlib only.

Designed for low-memory hosts (Raspberry Pi 4, 2GB). No third-party deps.
Fetches roadmap flowcharts from roadmap.sh, flattens them into a linear
learning order, and tracks progress in a local JSON file.
"""

import argparse
import heapq
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict

BASE = "https://roadmap.sh"
UA = "hermes-roadmap-tutor/1.0 (+https://github.com/)"

HOME = os.environ.get("ROADMAP_TUTOR_HOME") or os.path.join(
    os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes"), "roadmap-tutor"
)
CACHE = os.path.join(HOME, "cache")
STATE_PATH = os.path.join(HOME, "state.json")
CACHE_TTL = int(os.environ.get("ROADMAP_TUTOR_TTL", 60 * 60 * 24 * 14))


# ---------------------------------------------------------------- utilities


def _ensure_dirs():
    os.makedirs(CACHE, exist_ok=True)


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _cached(name, url, ttl=CACHE_TTL):
    _ensure_dirs()
    path = os.path.join(CACHE, name)
    if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < ttl:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    body = _get(url)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(body)
    os.replace(tmp, path)
    return body


def load_state():
    if not os.path.exists(STATE_PATH):
        return {"version": 1, "active": None, "roadmaps": {}}
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except ValueError:
            return {"version": 1, "active": None, "roadmaps": {}}


def save_state(state):
    _ensure_dirs()
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(tmp, STATE_PATH)


def die(msg, code=1):
    print(json.dumps({"error": msg}, indent=2))
    sys.exit(code)


# ------------------------------------------------------------------ parsing


def _box(node):
    """Bounding box in flowchart coordinates.

    `style.width/height` is the authored size; `measured` is the rendered size
    and is unreliable for grouping (roadmap.sh pads it). Prefer style.
    """
    x = node["position"]["x"]
    y = node["position"]["y"]
    style = node.get("style") or {}
    measured = node.get("measured") or {}
    w = style.get("width") or measured.get("width") or node.get("width") or 120
    h = style.get("height") or measured.get("height") or node.get("height") or 45
    return x, y, x + w, y + h


def _gap(a, b):
    """Squared edge-to-edge distance between two boxes, biased vertically.

    Horizontal separation is weighted heavier because roadmap.sh columns are
    semantically distinct tracks, while vertical proximity means "belongs to
    the heading above".
    """
    dx = max(b[0] - a[2], a[0] - b[2], 0)
    dy = max(b[1] - a[3], a[1] - b[3], 0)
    return (dx * 1.4) ** 2 + dy ** 2


def fetch_roadmap(slug, refresh=False):
    ttl = 0 if refresh else CACHE_TTL
    raw = _cached("roadmap-%s.json" % slug, "%s/%s.json" % (BASE, slug), ttl)
    return json.loads(raw)


def flatten(doc):
    """Turn a roadmap.sh reactflow graph into an ordered list of steps.

    Order = the flowchart's own spine (edges between topic nodes), with each
    topic's subtopics attached immediately after it. Falls back to vertical
    layout position wherever edges are missing.
    """
    nodes = {n["id"]: n for n in doc.get("nodes", [])}
    topics = [n for n in doc["nodes"] if n["type"] == "topic"]
    subs = [n for n in doc["nodes"] if n["type"] == "subtopic"]
    tset = {t["id"] for t in topics}

    incoming = defaultdict(list)
    outgoing = defaultdict(list)
    for e in doc.get("edges", []):
        s, t = e.get("source"), e.get("target")
        if s in nodes and t in nodes:
            outgoing[s].append(t)
            incoming[t].append(s)

    # --- order the topics ------------------------------------------------
    # Topological sort over topic-to-topic edges. Ties (and disjoint
    # components) are broken by layout position, so a roadmap whose flowchart
    # forks into parallel tracks still reads top-to-bottom. A heap rather than
    # a FIFO queue keeps separate components from interleaving.
    ypos = {t["id"]: (t["position"]["y"], t["position"]["x"]) for t in topics}
    indeg = {t["id"]: len([s for s in incoming[t["id"]] if s in tset]) for t in topics}

    frontier = [(ypos[tid], tid) for tid, d in indeg.items() if d == 0]
    heapq.heapify(frontier)
    ordered, seen = [], set()
    remaining = set(tset)

    while remaining:
        if not frontier:
            # Cycle, or a component with no root: seed from the topmost
            # unvisited topic so nothing is ever stranded.
            tid = min(remaining, key=lambda i: ypos[i])
            heapq.heappush(frontier, (ypos[tid], tid))
        _, tid = heapq.heappop(frontier)
        if tid in seen:
            continue
        seen.add(tid)
        remaining.discard(tid)
        ordered.append(tid)
        for m in outgoing[tid]:
            if m in tset and m not in seen:
                indeg[m] -= 1
                if indeg[m] <= 0:
                    heapq.heappush(frontier, (ypos[m], m))

    # --- attach subtopics to topics --------------------------------------
    # Three signals, in order of trust:
    #   1. an explicit edge from a topic  (authoritative)
    #   2. shared membership in a `section` box  (visual grouping)
    #   3. nearest topic by edge-to-edge distance  (layout fallback)
    sections = [n for n in doc["nodes"] if n["type"] == "section"]
    learnable = topics + subs

    sec_of, sec_members = {}, defaultdict(list)
    for sec in sections:
        x1, y1, x2, y2 = _box(sec)
        for n in learnable:
            nx, ny = n["position"]["x"], n["position"]["y"]
            if x1 - 6 <= nx <= x2 + 6 and y1 - 6 <= ny <= y2 + 6:
                sec_of[n["id"]] = sec["id"]
                sec_members[sec["id"]].append(n)

    # A section may carry a floating `label` node as its caption.
    labels = [
        n
        for n in doc["nodes"]
        if n["type"] == "label" and (n.get("data") or {}).get("label", "").strip()
    ]
    sec_caption = {}
    for sec in sections:
        near = sorted(labels, key=lambda l: _gap(_box(sec), _box(l)))
        if near and _gap(_box(sec), _box(near[0])) <= 60 ** 2:
            sec_caption[sec["id"]] = near[0]["data"]["label"].strip()

    def nearest_topic(bb):
        best, bd = None, None
        for t in topics:
            d = _gap(bb, _box(t))
            if bd is None or d < bd:
                bd, best = d, t["id"]
        return best

    parent = {}
    for sec in sections:
        members = sec_members[sec["id"]]
        tops = [m for m in members if m["type"] == "topic"]
        owner = (
            min(tops, key=lambda n: n["position"]["y"])["id"]
            if tops
            else nearest_topic(_box(sec))
        )
        for m in members:
            if m["type"] == "subtopic":
                parent[m["id"]] = owner

    for s in subs:
        direct = [p for p in incoming[s["id"]] if p in tset]
        if direct:
            parent[s["id"]] = direct[0]
        elif s["id"] not in parent:
            parent[s["id"]] = nearest_topic(_box(s))

    children = defaultdict(list)
    for s in subs:
        children[parent[s["id"]]].append(s)
    for k in children:
        children[k].sort(key=lambda n: (n["position"]["y"], n["position"]["x"]))

    steps = []
    for tid in ordered:
        t = nodes[tid]
        label = (t.get("data") or {}).get("label", "").strip()
        if not label:
            continue
        steps.append(
            {"id": tid, "title": label, "kind": "topic", "parent": None, "group": None}
        )
        for s in children[tid]:
            slabel = (s.get("data") or {}).get("label", "").strip()
            if not slabel:
                continue
            steps.append(
                {
                    "id": s["id"],
                    "title": slabel,
                    "kind": "subtopic",
                    "parent": label,
                    "group": sec_caption.get(sec_of.get(s["id"])),
                }
            )

    placed = {s["id"] for s in steps}
    for s in sorted(subs, key=lambda n: (n["position"]["y"], n["position"]["x"])):
        if s["id"] in placed:
            continue
        label = (s.get("data") or {}).get("label", "").strip()
        if label:
            steps.append(
                {
                    "id": s["id"],
                    "title": label,
                    "kind": "subtopic",
                    "parent": None,
                    "group": sec_caption.get(sec_of.get(s["id"])),
                }
            )
    return steps


def roadmap_meta(doc):
    title = doc.get("title")
    if isinstance(title, dict):
        title = title.get("page") or title.get("card")
    year = time.strftime("%Y")
    desc = (doc.get("description") or "").replace("@currentYear@", year)
    return {"slug": doc.get("slug"), "title": title or doc.get("slug"), "description": desc}


# ------------------------------------------------------------------ content

RESOURCE_TAG = re.compile(r"\[@(\w+)@([^\]]*)\]\(([^)]+)\)")


def fetch_content(slug, node_id, refresh=False):
    """Return (markdown_body, resources) for one node, or (None, []).

    roadmap.sh serves the write-up as `description` and the further-reading
    links as a structured `resources` array. Older payloads inline the links
    in the markdown as `[@type@ Title](url)` instead, so handle both.
    """
    ttl = 0 if refresh else CACHE_TTL
    url = "%s/api/v1-official-roadmap-topic/%s/%s" % (BASE, slug, node_id)
    try:
        raw = _cached("topic-%s-%s.json" % (slug, node_id), url, ttl)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, []
        raise
    try:
        doc = json.loads(raw)
    except ValueError:
        return None, []
    resources = [
        {
            "type": r.get("type") or "link",
            "title": (r.get("title") or "").strip(),
            "url": (r.get("url") or "").strip(),
        }
        for r in (doc.get("resources") or [])
        if r.get("url")
    ]
    return doc.get("description") or None, resources


def split_content(md, resources=None):
    """Strip inline resource links out of the prose and merge them in."""
    resources = list(resources or [])
    if not md:
        return "", resources
    seen = {r["url"] for r in resources}
    for kind, label, href in RESOURCE_TAG.findall(md):
        href = href.strip()
        if href not in seen:
            seen.add(href)
            resources.append({"type": kind, "title": label.strip(), "url": href})
    body_lines = []
    for line in md.splitlines():
        if RESOURCE_TAG.search(line):
            continue
        if line.strip().lower().startswith("visit the following resources"):
            continue
        body_lines.append(line)
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(body_lines).strip())
    return body, resources


# ------------------------------------------------------------------ tracking


def track(state, slug, create=True):
    rm = state["roadmaps"].get(slug)
    if rm is None and create:
        rm = {"cursor": 0, "done": [], "skipped": [], "notes": {}, "started": _now()}
        state["roadmaps"][slug] = rm
    return rm


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def resolve_slug(state, slug):
    slug = slug or state.get("active")
    if not slug:
        die("No active roadmap. Run: roadmap.py start <slug>  (see: roadmap.py list)")
    return slug


def progress_of(rm, steps):
    done = set(rm["done"])
    skipped = set(rm["skipped"])
    total = len(steps)
    complete = len([s for s in steps if s["id"] in done])
    return {
        "total": total,
        "done": complete,
        "skipped": len([s for s in steps if s["id"] in skipped]),
        "remaining": total - complete,
        "percent": round(100.0 * complete / total, 1) if total else 0.0,
    }


def next_index(rm, steps):
    handled = set(rm["done"]) | set(rm["skipped"])
    for i, s in enumerate(steps):
        if s["id"] not in handled:
            return i
    return None


# ------------------------------------------------------------------ commands


def cmd_list(args):
    slugs = KNOWN_ROADMAPS
    if args.query:
        q = args.query.lower()
        slugs = [s for s in slugs if q in s]
    print(json.dumps({"roadmaps": slugs, "count": len(slugs)}, indent=2))


def cmd_start(args):
    state = load_state()
    slug = args.slug
    doc = fetch_roadmap(slug, args.refresh)
    steps = flatten(doc)
    if not steps:
        die("Roadmap '%s' has no learnable steps." % slug)
    rm = track(state, slug)
    state["active"] = slug
    save_state(state)
    meta = roadmap_meta(doc)
    print(
        json.dumps(
            {
                "started": slug,
                "title": meta["title"],
                "description": meta["description"],
                "steps": len(steps),
                "progress": progress_of(rm, steps),
                "hint": "Run 'next' to get your first topic.",
            },
            indent=2,
        )
    )


def _render(slug, steps, idx, rm, refresh=False, brief=False):
    step = steps[idx]
    md, api_resources = fetch_content(slug, step["id"], refresh)
    body, resources = split_content(md, api_resources)
    if brief and body:
        body = body.split("\n\n")[0] if "\n\n" in body else body
    out = {
        "roadmap": slug,
        "position": "%d/%d" % (idx + 1, len(steps)),
        "id": step["id"],
        "title": step["title"],
        "kind": step["kind"],
        "section": step["parent"],
        "group": step.get("group"),
        "content": body or "(No write-up on roadmap.sh for this node - explain it yourself.)",
        "resources": resources,
        "progress": progress_of(rm, steps),
    }
    return out


def cmd_next(args):
    state = load_state()
    slug = resolve_slug(state, args.slug)
    doc = fetch_roadmap(slug, args.refresh)
    steps = flatten(doc)
    rm = track(state, slug)
    state["active"] = slug
    idx = next_index(rm, steps)
    if idx is None:
        save_state(state)
        print(
            json.dumps(
                {
                    "roadmap": slug,
                    "status": "complete",
                    "message": "Every step is done or skipped. Pick a new roadmap.",
                    "progress": progress_of(rm, steps),
                },
                indent=2,
            )
        )
        return
    rm["cursor"] = idx
    rm["last_seen"] = _now()
    save_state(state)
    print(json.dumps(_render(slug, steps, idx, rm, args.refresh, args.brief), indent=2))


def cmd_current(args):
    state = load_state()
    slug = resolve_slug(state, args.slug)
    doc = fetch_roadmap(slug, args.refresh)
    steps = flatten(doc)
    rm = track(state, slug)
    idx = min(rm.get("cursor", 0), len(steps) - 1)
    print(json.dumps(_render(slug, steps, idx, rm, args.refresh, args.brief), indent=2))


def cmd_done(args):
    state = load_state()
    slug = resolve_slug(state, args.slug)
    doc = fetch_roadmap(slug)
    steps = flatten(doc)
    rm = track(state, slug)
    idx = rm.get("cursor", 0)
    if args.id:
        matches = [i for i, s in enumerate(steps) if s["id"] == args.id]
        if not matches:
            matches = [
                i
                for i, s in enumerate(steps)
                if args.id.lower() in s["title"].lower()
            ]
        if not matches:
            die("No step matching '%s'." % args.id)
        idx = matches[0]
    if idx >= len(steps):
        die("Cursor out of range.")
    step = steps[idx]
    if step["id"] not in rm["done"]:
        rm["done"].append(step["id"])
    if step["id"] in rm["skipped"]:
        rm["skipped"].remove(step["id"])
    if args.note:
        rm["notes"][step["id"]] = args.note
    rm["cursor"] = min(idx + 1, len(steps) - 1)
    rm["last_seen"] = _now()
    save_state(state)
    print(
        json.dumps(
            {
                "marked_done": step["title"],
                "roadmap": slug,
                "progress": progress_of(rm, steps),
                "up_next": steps[next_index(rm, steps)]["title"]
                if next_index(rm, steps) is not None
                else None,
            },
            indent=2,
        )
    )


def cmd_skip(args):
    state = load_state()
    slug = resolve_slug(state, args.slug)
    doc = fetch_roadmap(slug)
    steps = flatten(doc)
    rm = track(state, slug)
    idx = rm.get("cursor", 0)
    if idx >= len(steps):
        die("Cursor out of range.")
    step = steps[idx]
    if step["id"] not in rm["skipped"] and step["id"] not in rm["done"]:
        rm["skipped"].append(step["id"])
    rm["cursor"] = min(idx + 1, len(steps) - 1)
    save_state(state)
    print(
        json.dumps(
            {"skipped": step["title"], "progress": progress_of(rm, steps)}, indent=2
        )
    )


def cmd_status(args):
    state = load_state()
    out = {"active": state.get("active"), "roadmaps": {}}
    for slug, rm in state["roadmaps"].items():
        try:
            steps = flatten(fetch_roadmap(slug))
        except Exception as exc:  # offline / cache miss
            out["roadmaps"][slug] = {"error": str(exc)}
            continue
        p = progress_of(rm, steps)
        nxt = next_index(rm, steps)
        p["up_next"] = steps[nxt]["title"] if nxt is not None else None
        p["started"] = rm.get("started")
        p["last_seen"] = rm.get("last_seen")
        out["roadmaps"][slug] = p
    print(json.dumps(out, indent=2))


def cmd_outline(args):
    state = load_state()
    slug = resolve_slug(state, args.slug)
    doc = fetch_roadmap(slug, args.refresh)
    steps = flatten(doc)
    rm = track(state, slug, create=False) or {"done": [], "skipped": [], "cursor": 0}
    done, skipped = set(rm["done"]), set(rm["skipped"])
    lines = []
    for i, s in enumerate(steps):
        mark = "x" if s["id"] in done else ("~" if s["id"] in skipped else " ")
        prefix = "" if s["kind"] == "topic" else "    "
        lines.append("%3d. [%s] %s%s" % (i + 1, mark, prefix, s["title"]))
    print("\n".join(lines))


def cmd_search(args):
    state = load_state()
    slug = resolve_slug(state, args.slug)
    steps = flatten(fetch_roadmap(slug))
    q = args.query.lower()
    hits = [
        {"index": i + 1, "id": s["id"], "title": s["title"], "section": s["parent"]}
        for i, s in enumerate(steps)
        if q in s["title"].lower()
    ]
    print(json.dumps({"query": args.query, "matches": hits}, indent=2))


def cmd_goto(args):
    state = load_state()
    slug = resolve_slug(state, args.slug)
    steps = flatten(fetch_roadmap(slug))
    rm = track(state, slug)
    idx = None
    if args.target.isdigit():
        idx = int(args.target) - 1
    else:
        for i, s in enumerate(steps):
            if s["id"] == args.target or args.target.lower() in s["title"].lower():
                idx = i
                break
    if idx is None or not (0 <= idx < len(steps)):
        die("Could not resolve '%s' to a step." % args.target)
    rm["cursor"] = idx
    state["active"] = slug
    save_state(state)
    print(json.dumps(_render(slug, steps, idx, rm, False, args.brief), indent=2))


def cmd_switch(args):
    state = load_state()
    if args.slug not in state["roadmaps"]:
        die("Not tracking '%s'. Run: start %s" % (args.slug, args.slug))
    state["active"] = args.slug
    save_state(state)
    print(json.dumps({"active": args.slug}, indent=2))


def cmd_reset(args):
    state = load_state()
    slug = resolve_slug(state, args.slug)
    if slug in state["roadmaps"]:
        del state["roadmaps"][slug]
    if state.get("active") == slug:
        state["active"] = None
    save_state(state)
    print(json.dumps({"reset": slug}, indent=2))


def cmd_prefetch(args):
    state = load_state()
    slug = resolve_slug(state, args.slug)
    steps = flatten(fetch_roadmap(slug, args.refresh))
    limit = args.count or len(steps)
    rm = track(state, slug, create=False) or {"done": [], "skipped": [], "cursor": 0}
    start = rm.get("cursor", 0)
    got, missing = 0, 0
    for s in steps[start : start + limit]:
        try:
            if fetch_content(slug, s["id"])[0]:
                got += 1
            else:
                missing += 1
        except Exception:
            missing += 1
    print(
        json.dumps(
            {"roadmap": slug, "cached": got, "no_content": missing, "from": start + 1},
            indent=2,
        )
    )


# roadmap.sh official roadmap slugs (roadmaps/ in the upstream repo).
KNOWN_ROADMAPS = [
    "ai-agents", "ai-data-scientist", "ai-engineer", "ai-product-builder",
    "ai-red-teaming", "android", "angular", "api-design", "aspnet-core",
    "aws", "backend", "backend-beginner", "bi-analyst", "blockchain", "c",
    "claude-code", "cloudflare", "code-review", "computer-science", "cpp",
    "css", "cyber-security", "data-analyst", "data-engineer",
    "datastructures-and-algorithms", "design-system", "devops",
    "devops-beginner", "devrel", "devsecops", "django", "docker",
    "elasticsearch", "engineering-manager", "flutter",
    "forward-deployed-engineer", "frontend", "frontend-beginner",
    "full-stack", "game-developer", "git-github", "git-github-beginner",
    "golang", "graphql", "html", "ios", "java", "javascript", "kotlin",
    "kubernetes", "laravel", "leetcode", "linux", "machine-learning", "mlops",
    "mongodb", "network-engineer", "nextjs", "nodejs", "openclaw", "php",
    "postgresql-dba", "power-bi", "product-design", "product-manager",
    "prompt-engineering", "python", "python-data-analysis", "qa", "react",
    "react-native", "redis", "ruby", "ruby-on-rails", "rust", "scala",
    "server-side-game-developer", "shell-bash", "software-architect",
    "software-design-architecture", "spring-boot", "sql", "swift-ui",
    "system-design", "technical-writer", "terraform", "typescript",
    "ux-design", "vibe-coding", "vue", "wordpress"
]


def main():
    p = argparse.ArgumentParser(prog="roadmap.py", description=__doc__)
    sub = p.add_subparsers(dest="cmd")

    def add(name, fn, **kw):
        sp = sub.add_parser(name, **kw)
        sp.set_defaults(fn=fn)
        return sp

    sp = add("list", cmd_list, help="List known roadmap slugs")
    sp.add_argument("query", nargs="?")

    sp = add("start", cmd_start, help="Start tracking a roadmap")
    sp.add_argument("slug")
    sp.add_argument("--refresh", action="store_true")

    sp = add("next", cmd_next, help="Get the next unfinished step")
    sp.add_argument("--slug")
    sp.add_argument("--refresh", action="store_true")
    sp.add_argument("--brief", action="store_true")

    sp = add("current", cmd_current, help="Re-show the current step")
    sp.add_argument("--slug")
    sp.add_argument("--refresh", action="store_true")
    sp.add_argument("--brief", action="store_true")

    sp = add("done", cmd_done, help="Mark the current (or named) step complete")
    sp.add_argument("id", nargs="?")
    sp.add_argument("--slug")
    sp.add_argument("--note")

    sp = add("skip", cmd_skip, help="Skip the current step")
    sp.add_argument("--slug")

    add("status", cmd_status, help="Progress across all tracked roadmaps")

    sp = add("outline", cmd_outline, help="Print the full checklist")
    sp.add_argument("--slug")
    sp.add_argument("--refresh", action="store_true")

    sp = add("search", cmd_search, help="Find a step by title")
    sp.add_argument("query")
    sp.add_argument("--slug")

    sp = add("goto", cmd_goto, help="Jump to a step by number, id, or title")
    sp.add_argument("target")
    sp.add_argument("--slug")
    sp.add_argument("--brief", action="store_true")

    sp = add("switch", cmd_switch, help="Change the active roadmap")
    sp.add_argument("slug")

    sp = add("reset", cmd_reset, help="Delete progress for a roadmap")
    sp.add_argument("--slug")

    sp = add("prefetch", cmd_prefetch, help="Warm the offline cache")
    sp.add_argument("--slug")
    sp.add_argument("--count", type=int, default=20)
    sp.add_argument("--refresh", action="store_true")

    args = p.parse_args()
    if not getattr(args, "fn", None):
        p.print_help()
        sys.exit(2)
    try:
        args.fn(args)
    except urllib.error.HTTPError as e:
        die("HTTP %s fetching from roadmap.sh (is the slug right? try 'list')" % e.code)
    except urllib.error.URLError as e:
        die("Network error: %s. Cached steps still work offline." % e.reason)


if __name__ == "__main__":
    main()
