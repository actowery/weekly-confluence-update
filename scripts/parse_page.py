#!/usr/bin/env python3
"""
ADF parser and patch builder for Confluence weekly-report pages.

Subcommands:
  sections <adf_file> --user-id <id> --team-config <path>
      Emit a JSON section map identifying prompts, team-ownership blocks,
      and global team-only rows, plus which of those the user owns.

  dates --title <page_title> | --adf <adf_file>
      Extract a date range (ISO start/end). Exits non-zero if unparseable.

  build-patch <adf_file> --drafts <drafts_file> --team-name <name>
      Apply drafts to a copy of the ADF and emit the modified ADF to stdout.

The drafts file is JSON keyed by section path:
  {
    "table[0]/row[4]/cell[1]": {
      "kind": "append_to_team_block" | "new_team_block" | "team_only_row_contribution",
      "team_name": "<your team>",
      "bullets": ["...", "..."]
    }
  }

No network calls. No state. Reads JSON in, writes JSON out.
"""

import argparse
import copy
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path


DEFAULT_TEAM_ONLY_ROW_LABELS = [
    "product releases completed",
    "releases",
    "challenges",
    "organization",
    "hiring",
    "resignations",
    "organization, hiring, resignations",
]

DEFAULT_PROMPT_PHRASE = r"provide weekly updates"

# Populated at command entry from team config, with the defaults above as fallback.
# Mutable module-level state so helper functions (which run inside the module)
# can see overrides without threading an extra argument through every helper.
TEAM_ONLY_ROW_LABELS = list(DEFAULT_TEAM_ONLY_ROW_LABELS)
PROMPT_PHRASE_RE = re.compile(DEFAULT_PROMPT_PHRASE, re.IGNORECASE)


def apply_team_layout_overrides(team_cfg):
    global TEAM_ONLY_ROW_LABELS, PROMPT_PHRASE_RE
    layout = (team_cfg or {}).get("page_layout") or {}
    labels = layout.get("team_only_row_labels")
    if isinstance(labels, list) and labels:
        TEAM_ONLY_ROW_LABELS = [str(x).lower() for x in labels]
    phrase = layout.get("prompt_phrase_regex")
    if isinstance(phrase, str) and phrase.strip():
        PROMPT_PHRASE_RE = re.compile(phrase, re.IGNORECASE)


def load_adf(path):
    """Load ADF from a file.

    Accepts either a raw ADF doc ({type: 'doc', content: [...]}) or the full
    getConfluencePage response wrapper ({title, body: <adf>, ...}). Returns a
    dict with at least 'content' and usually 'title' at the top level.
    """
    text = Path(path).read_text()
    data = json.loads(text)
    if isinstance(data, dict) and data.get("type") == "doc":
        return data
    if isinstance(data, dict) and isinstance(data.get("body"), dict) and data["body"].get("type") == "doc":
        body = data["body"]
        if "title" in data and "title" not in body:
            body["title"] = data["title"]
        return body
    return data


def walk(node, path="", out=None):
    """Yield (path, node) for every dict node in the ADF tree."""
    if out is None:
        out = []
    out.append((path, node))
    content = node.get("content") if isinstance(node, dict) else None
    if isinstance(content, list):
        by_type_counter = {}
        for child in content:
            if not isinstance(child, dict):
                continue
            t = child.get("type", "node")
            i = by_type_counter.get(t, 0)
            by_type_counter[t] = i + 1
            child_path = f"{path}/{t}[{i}]" if path else f"{t}[{i}]"
            walk(child, child_path, out)
    return out


def text_of(node):
    """Concatenate all descendant text nodes, preserving spaces."""
    if not isinstance(node, dict):
        return ""
    if node.get("type") == "text":
        return node.get("text", "")
    if node.get("type") == "hardBreak":
        return " "
    parts = []
    for child in node.get("content", []) or []:
        parts.append(text_of(child))
    return "".join(parts)


def mentions_in(node):
    """Return list of {id, text} for every mention node in the subtree."""
    out = []
    if not isinstance(node, dict):
        return out
    if node.get("type") == "mention":
        a = node.get("attrs", {}) or {}
        out.append({"id": a.get("id"), "text": a.get("text", "")})
    for child in node.get("content", []) or []:
        out.extend(mentions_in(child))
    return out


def is_strong_only_paragraph(node):
    """True if the paragraph's only visible content is a single strong-marked text."""
    if not isinstance(node, dict) or node.get("type") != "paragraph":
        return None
    content = [c for c in (node.get("content") or []) if c.get("type") == "text" and c.get("text", "").strip()]
    if len(content) != 1:
        return None
    text_node = content[0]
    marks = text_node.get("marks") or []
    if any(m.get("type") == "strong" for m in marks):
        return text_node.get("text", "").strip()
    return None


def find_enclosing_cell_path(path):
    """Given a deep path like 'table[0]/.../cell[1]/paragraph[2]', return the cell path."""
    parts = path.split("/")
    for i in range(len(parts) - 1, -1, -1):
        if parts[i].startswith("tableCell") or parts[i].startswith("tableHeader") or parts[i].startswith("cell"):
            return "/".join(parts[: i + 1])
    return None


def enclosing_row_path(path):
    parts = path.split("/")
    out = []
    for p in parts:
        out.append(p)
        if p.startswith("tableRow"):
            return "/".join(out)
    return None


def row_cells(adf, row_path):
    """Return the list of (type, path, node) for each cell in the row, in visual order."""
    nodes = walk(adf)
    row = next((n for p, n in nodes if p == row_path), None)
    if not row:
        return []
    out = []
    counters = {"tableHeader": 0, "tableCell": 0}
    for child in row.get("content", []) or []:
        t = child.get("type")
        if t in counters:
            i = counters[t]
            counters[t] += 1
            out.append((t, f"{row_path}/{t}[{i}]", child))
    return out


def left_column_label(adf, cell_path_or_row_path):
    """Clean short label for a row: first paragraph of the first cell, pre-prompt only."""
    row_path = enclosing_row_path(cell_path_or_row_path) if "tableRow" in cell_path_or_row_path else cell_path_or_row_path
    if not row_path:
        return ""
    cells = row_cells(adf, row_path)
    if not cells:
        return ""
    first = cells[0][2]
    # First paragraph's text, cut at the first prompt phrase if any.
    for child in first.get("content", []) or []:
        if child.get("type") == "paragraph":
            txt = text_of(child).strip()
            # Stop at prompt-style phrasing to keep the label clean.
            m = PROMPT_PHRASE_RE.search(txt)
            if m:
                txt = txt[: m.start()].rstrip(" -:")
            if txt:
                return txt
    return text_of(first).strip()[:120]


def cmd_sections(args):
    adf = load_adf(args.adf_file)
    team_cfg = json.loads(Path(args.team_config).read_text()) if args.team_config else {}
    apply_team_layout_overrides(team_cfg)
    team_name = team_cfg.get("team_name", "")
    user_id = args.user_id

    nodes = walk(adf)

    # Collect all prompts (mention-bearing paragraphs with "provide weekly updates") and team blocks,
    # keyed by their enclosing row so we can later pair left-cell prompts with right-cell content.
    row_info = {}  # row_path -> {prompts: [...], team_blocks: [...], cells: [...]}

    for path, node in nodes:
        if not isinstance(node, dict):
            continue
        row_path = enclosing_row_path(path)
        if not row_path or row_path == path:
            continue
        entry = row_info.setdefault(row_path, {"prompts": [], "team_blocks": []})

        if node.get("type") == "paragraph":
            txt = text_of(node)
            if PROMPT_PHRASE_RE.search(txt):
                ms = [m for m in mentions_in(node) if m.get("id")]
                if ms:
                    entry["prompts"].append({
                        "prompt_path": path,
                        "cell_path": find_enclosing_cell_path(path),
                        "prompt_text": txt.strip(),
                        "mentioned_account_ids": sorted({m["id"] for m in ms}),
                        "topics": [],
                    })

            team = is_strong_only_paragraph(node)
            if team:
                entry["team_blocks"].append({
                    "path": path,
                    "cell_path": find_enclosing_cell_path(path),
                    "team_name": team,
                })

    # Attach topics: the bullet list immediately following each prompt paragraph in the same cell.
    for row_path, entry in row_info.items():
        for prompt in entry["prompts"]:
            cell_path = prompt["cell_path"]
            in_cell = [(p, n) for p, n in nodes if p.startswith(cell_path + "/") and isinstance(n, dict)]
            past = False
            for p, n in in_cell:
                if p == prompt["prompt_path"]:
                    past = True
                    continue
                if past and n.get("type") == "bulletList":
                    prompt["topics"] = [text_of(li).strip() for li in n.get("content") or []]
                    break
                if past and n.get("type") == "paragraph":
                    break

    sections = []
    skipped = []

    # Walk rows in document order.
    for path, node in nodes:
        if not isinstance(node, dict) or node.get("type") != "tableRow":
            continue
        row_path = path
        entry = row_info.get(row_path, {"prompts": [], "team_blocks": []})
        cells = row_cells(adf, row_path)
        if not cells:
            continue

        row_label = left_column_label(adf, row_path)
        # The "update cell" is conventionally the last cell in the row (typically `tableCell[0]`
        # in a 2-column Category|Update table).
        update_cell_type, update_cell_path, _ = cells[-1]

        user_tagged_prompts = [p for p in entry["prompts"] if user_id in p["mentioned_account_ids"]]
        team_block = next(
            (b for b in entry["team_blocks"] if b["team_name"].lower() == team_name.lower()),
            None,
        )

        # Global team-only rows (Releases/Challenges/Org/Hiring).
        row_label_lc = row_label.lower()
        is_team_only_row = any(needle in row_label_lc for needle in TEAM_ONLY_ROW_LABELS)

        if is_team_only_row:
            sections.append({
                "kind": "team_only_row",
                "row_path": row_path,
                "row_label": row_label,
                "update_cell_path": update_cell_path,
            })
            continue

        if user_tagged_prompts and team_block:
            sections.append({
                "kind": "explicit_assignment_with_team_block",
                "row_path": row_path,
                "row_label": row_label,
                "update_cell_path": update_cell_path,
                "prompts": user_tagged_prompts,
                "team_block_path": team_block["path"],
                "team_name": team_block["team_name"],
            })
        elif user_tagged_prompts:
            sections.append({
                "kind": "explicit_assignment_no_team_block",
                "row_path": row_path,
                "row_label": row_label,
                "update_cell_path": update_cell_path,
                "prompts": user_tagged_prompts,
                "team_name": team_name,
            })
        elif team_block:
            sections.append({
                "kind": "team_owned",
                "row_path": row_path,
                "row_label": row_label,
                "update_cell_path": update_cell_path,
                "team_block_path": team_block["path"],
                "team_name": team_block["team_name"],
            })
        elif entry["prompts"]:
            skipped.append({
                "row_path": row_path,
                "row_label": row_label,
                "reason": "user not @-mentioned and no team block present",
                "other_team_mentions": sorted({
                    aid for p in entry["prompts"] for aid in p["mentioned_account_ids"]
                }),
            })

    out = {
        "page_title": adf.get("title", ""),
        "user_id": user_id,
        "team_name": team_name,
        "sections": sections,
        "skipped_rows": skipped,
    }
    print(json.dumps(out, indent=2))


# -------- date extraction --------

MONTHS = {m.lower(): i for i, m in enumerate(
    ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
)}
MONTHS.update({m.lower(): i for i, m in enumerate(
    ["", "January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"]
)})


def parse_dates_from_text(text):
    """Return (start_iso, end_iso) or None."""
    if not text:
        return None

    # Pattern: "13 Apr - 17 Apr 2026"
    m = re.search(
        r"(\d{1,2})\s+([A-Za-z]+)\s*[\-\u2013]\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})",
        text,
    )
    if m:
        d1, mo1, d2, mo2, yr = m.groups()
        mo1i, mo2i = MONTHS.get(mo1.lower()), MONTHS.get(mo2.lower())
        if mo1i and mo2i:
            return (
                date(int(yr), mo1i, int(d1)).isoformat(),
                date(int(yr), mo2i, int(d2)).isoformat(),
            )

    # Pattern: "2026-04-13 to 2026-04-17" or "2026-04-13 - 2026-04-17"
    m = re.search(r"(\d{4}-\d{2}-\d{2})\s*(?:to|[\-\u2013])\s*(\d{4}-\d{2}-\d{2})", text)
    if m:
        return m.group(1), m.group(2)

    # Pattern: "Week of 2026-04-13"
    m = re.search(r"week of\s+(\d{4}-\d{2}-\d{2})", text, re.IGNORECASE)
    if m:
        start = datetime.fromisoformat(m.group(1)).date()
        # Assume Monday start, Friday end.
        from datetime import timedelta
        return start.isoformat(), (start + timedelta(days=4)).isoformat()

    # Pattern: "Apr 13, 2026"
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", text)
    if m:
        mo, d1, yr = m.groups()
        moi = MONTHS.get(mo.lower())
        if moi:
            from datetime import timedelta
            start = date(int(yr), moi, int(d1))
            return start.isoformat(), (start + timedelta(days=4)).isoformat()

    return None


def cmd_dates(args):
    text = args.title
    if args.adf:
        adf = load_adf(args.adf)
        text = text or adf.get("title") or text_of(adf)
    parsed = parse_dates_from_text(text or "")
    if not parsed:
        print(f"Could not parse a date range from: {text!r}", file=sys.stderr)
        sys.exit(2)
    print(json.dumps({"start": parsed[0], "end": parsed[1]}))


# -------- patch builder --------

SENTINEL_KEY = "_skillAdded"


def _mark(node):
    node.setdefault("attrs", {})[SENTINEL_KEY] = True
    return node


def paragraph_strong(text, mark=True):
    n = {
        "type": "paragraph",
        "content": [{"type": "text", "text": text, "marks": [{"type": "strong"}]}],
    }
    return _mark(n) if mark else n


def paragraph_plain(text, mark=True):
    n = {"type": "paragraph", "content": [{"type": "text", "text": text}]}
    return _mark(n) if mark else n


def bullet_list(items, mark=True):
    n = {
        "type": "bulletList",
        "content": [
            {
                "type": "listItem",
                "content": [paragraph_plain(item, mark=False)],
            }
            for item in items
        ],
    }
    return _mark(n) if mark else n


def locate(adf, path):
    """Return (parent_list, index_in_parent, node) for the node at path, or (None, None, None)."""
    if not path:
        return None, None, adf
    parts = path.split("/")
    cur = adf
    parent_list = None
    idx = None
    for part in parts:
        m = re.match(r"([A-Za-z]+)\[(\d+)\]", part)
        if not m:
            return None, None, None
        t, i = m.group(1), int(m.group(2))
        content = cur.get("content") or []
        matches = [c for c in content if isinstance(c, dict) and c.get("type") == t]
        if i >= len(matches):
            return None, None, None
        target = matches[i]
        # Find absolute index in content for later insertion.
        abs_idx = content.index(target)
        parent_list = content
        idx = abs_idx
        cur = target
    return parent_list, idx, cur


def cmd_build_patch(args):
    adf = load_adf(args.adf_file)
    drafts = json.loads(Path(args.drafts).read_text())
    out = copy.deepcopy(adf)

    for cell_path, spec in drafts.items():
        kind = spec.get("kind")
        paragraphs = spec.get("paragraphs") or []
        bullets = spec.get("bullets") or []

        if not paragraphs and not bullets:
            continue

        if kind == "append_to_team_block":
            # Append paragraph nodes after the team-block heading paragraph, in the order given.
            block_path = spec.get("team_block_path") or cell_path
            parent, idx, node = locate(out, block_path)
            if parent is None:
                print(f"warn: could not locate team_block_path {block_path}", file=sys.stderr)
                continue
            insert_at = idx + 1
            for p in paragraphs:
                parent.insert(insert_at, paragraph_plain(p))
                insert_at += 1
            if bullets:
                parent.insert(insert_at, bullet_list(bullets))

        elif kind == "new_team_block":
            # Append a strong paragraph for the team name, then paragraphs (preferred) or bullets.
            parent, idx, cell = locate(out, cell_path)
            if cell is None:
                print(f"warn: could not locate update_cell_path {cell_path}", file=sys.stderr)
                continue
            cell.setdefault("content", []).append(paragraph_strong(spec["team_name"]))
            for p in paragraphs:
                cell["content"].append(paragraph_plain(p))
            if bullets:
                cell["content"].append(bullet_list(bullets))

        elif kind == "team_only_row_contribution":
            # Append "<TeamName>:" bold paragraph + bullets (or paragraphs) at end of the update cell.
            update_cell_path = spec.get("update_cell_path") or cell_path
            parent, idx, cell = locate(out, update_cell_path)
            if cell is None:
                print(f"warn: could not locate update_cell_path {update_cell_path}", file=sys.stderr)
                continue
            cell.setdefault("content", []).append(paragraph_strong(f"{spec['team_name']}:"))
            if bullets:
                cell["content"].append(bullet_list(bullets))
            for p in paragraphs:
                cell["content"].append(paragraph_plain(p))

        else:
            print(f"unknown patch kind: {kind!r} for {cell_path}", file=sys.stderr)

    print(json.dumps(out))


def cmd_strip_sentinels(args):
    """Remove _skillAdded sentinel attrs from an ADF tree. Use before publishing."""
    adf = load_adf(args.adf_file)

    def scrub(node):
        if not isinstance(node, dict):
            return
        attrs = node.get("attrs")
        if isinstance(attrs, dict) and SENTINEL_KEY in attrs:
            del attrs[SENTINEL_KEY]
            if not attrs:
                del node["attrs"]
        for child in node.get("content", []) or []:
            scrub(child)

    scrub(adf)
    print(json.dumps(adf))


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("sections")
    ps.add_argument("adf_file")
    ps.add_argument("--user-id", required=True)
    ps.add_argument("--team-config", required=True)
    ps.set_defaults(func=cmd_sections)

    pd = sub.add_parser("dates")
    pd.add_argument("--title", default=None)
    pd.add_argument("--adf", default=None)
    pd.set_defaults(func=cmd_dates)

    pb = sub.add_parser("build-patch")
    pb.add_argument("adf_file")
    pb.add_argument("--drafts", required=True)
    pb.set_defaults(func=cmd_build_patch)

    pstrip = sub.add_parser("strip-sentinels")
    pstrip.add_argument("adf_file")
    pstrip.set_defaults(func=cmd_strip_sentinels)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
