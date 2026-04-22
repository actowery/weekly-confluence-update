#!/usr/bin/env python3
"""
Render a Confluence ADF document to a standalone HTML preview file.

Nodes marked with attrs._skillAdded=true (the sentinel set by parse_page.py
build-patch) render with a yellow highlight so the reviewer can see exactly
what the skill intends to add before publishing.

Usage:
  render_preview.py <adf_file> --title "Weekly Report ..." --out /tmp/preview.html
"""

import argparse
import html
import json
from pathlib import Path


SENTINEL_KEY = "_skillAdded"


def is_added(node):
    return isinstance(node, dict) and (node.get("attrs") or {}).get(SENTINEL_KEY) is True


def render_text(node):
    text = html.escape(node.get("text", ""))
    for mark in node.get("marks") or []:
        t = mark.get("type")
        if t == "strong":
            text = f"<strong>{text}</strong>"
        elif t == "em":
            text = f"<em>{text}</em>"
        elif t == "code":
            text = f"<code>{text}</code>"
        elif t == "strike":
            text = f"<s>{text}</s>"
        elif t == "link":
            href = html.escape((mark.get("attrs") or {}).get("href", "#"))
            text = f'<a href="{href}">{text}</a>'
    return text


def render_node(node):
    if not isinstance(node, dict):
        return ""

    t = node.get("type")
    wrap_open, wrap_close = "", ""
    if is_added(node):
        wrap_open = '<span class="skill-added">'
        wrap_close = "</span>"

    if t == "text":
        return render_text(node)

    if t == "hardBreak":
        return "<br/>"

    if t == "mention":
        attrs = node.get("attrs") or {}
        txt = html.escape(attrs.get("text", "@mention"))
        return f'<span class="mention">{txt}</span>'

    if t == "status":
        attrs = node.get("attrs") or {}
        txt = html.escape(attrs.get("text", ""))
        color = attrs.get("color", "neutral")
        return f'<span class="status status-{color}">{txt}</span>'

    if t == "inlineCard":
        attrs = node.get("attrs") or {}
        href = html.escape(attrs.get("url", "#"))
        return f'<a class="inline-card" href="{href}">{href}</a>'

    children = "".join(render_node(c) for c in node.get("content") or [])

    if t == "paragraph":
        return f"{wrap_open}<p>{children}</p>{wrap_close}"
    if t == "heading":
        level = (node.get("attrs") or {}).get("level", 2)
        return f"{wrap_open}<h{level}>{children}</h{level}>{wrap_close}"
    if t == "bulletList":
        return f"{wrap_open}<ul>{children}</ul>{wrap_close}"
    if t == "orderedList":
        return f"{wrap_open}<ol>{children}</ol>{wrap_close}"
    if t == "listItem":
        return f"<li>{children}</li>"
    if t == "table":
        return f'<table class="adf-table">{children}</table>'
    if t == "tableRow":
        return f"<tr>{children}</tr>"
    if t == "tableHeader":
        return f"<th>{children}</th>"
    if t == "tableCell":
        return f"<td>{children}</td>"
    if t == "panel":
        ptype = (node.get("attrs") or {}).get("panelType", "info")
        return f'<div class="panel panel-{ptype}">{children}</div>'
    if t == "blockquote":
        return f"<blockquote>{children}</blockquote>"
    if t == "codeBlock":
        return f"<pre><code>{children}</code></pre>"
    if t == "rule":
        return "<hr/>"
    if t == "doc":
        return children

    # Unknown — pass through children.
    return children


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>{title} \u2014 Preview</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    max-width: 1100px; margin: 2em auto; padding: 0 1.5em; line-height: 1.5;
    color: #172b4d; background: #fff; }}
  h1 {{ border-bottom: 1px solid #dfe1e6; padding-bottom: 0.3em; }}
  .banner {{ background: #fffae6; border: 1px solid #ffc400; padding: 0.75em 1em;
    border-radius: 4px; margin: 1em 0 2em; font-size: 0.95em; }}
  .skill-added {{ background: #fff59d; border-left: 3px solid #f4a700; padding: 0.1em 0.3em;
    display: block; margin: 0.25em 0; border-radius: 2px; }}
  ul .skill-added, ol .skill-added {{ display: list-item; margin-left: 1em; }}
  .mention {{ background: #deebff; color: #0052cc; padding: 0 3px; border-radius: 3px;
    font-size: 0.92em; }}
  .status {{ display: inline-block; padding: 1px 6px; border-radius: 3px;
    font-size: 0.85em; font-weight: 600; }}
  .status-neutral {{ background: #dfe1e6; color: #42526e; }}
  .status-green {{ background: #e3fcef; color: #006644; }}
  .status-red {{ background: #ffebe6; color: #bf2600; }}
  .status-yellow {{ background: #fff0b3; color: #974f0c; }}
  .panel {{ border-left: 3px solid #4c9aff; background: #deebff; padding: 0.75em 1em;
    border-radius: 4px; margin: 1em 0; }}
  .panel-note {{ border-color: #ffab00; background: #fffae6; }}
  .panel-warning {{ border-color: #ff8b00; background: #fff4e6; }}
  .panel-success {{ border-color: #00875a; background: #e3fcef; }}
  .adf-table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
  .adf-table th, .adf-table td {{ border: 1px solid #dfe1e6; padding: 0.5em 0.75em;
    vertical-align: top; }}
  .adf-table th {{ background: #f4f5f7; text-align: left; }}
  .inline-card {{ border: 1px solid #dfe1e6; padding: 1px 6px; border-radius: 3px;
    text-decoration: none; color: #0052cc; font-size: 0.9em; }}
  code {{ background: #f4f5f7; padding: 1px 4px; border-radius: 3px; }}
  hr {{ border: none; border-top: 1px solid #dfe1e6; margin: 1.5em 0; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="banner">
  <strong>Preview only.</strong> Content highlighted in yellow is what this skill
  will append to the live page. Nothing else will change. Review carefully before approving.
</div>
{body}
</body>
</html>
"""


def main():
    p = argparse.ArgumentParser()
    p.add_argument("adf_file")
    p.add_argument("--title", default="Weekly Report")
    p.add_argument("--out", required=True)
    args = p.parse_args()

    adf = json.loads(Path(args.adf_file).read_text())
    body = render_node(adf)
    out = HTML_TEMPLATE.format(title=html.escape(args.title), body=body)
    Path(args.out).write_text(out)
    print(args.out)


if __name__ == "__main__":
    main()
