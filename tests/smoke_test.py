#!/usr/bin/env python3
"""
Smoke test — exercise every parse_page.py subcommand + render_preview.py
against the sanitized fixtures.

Run from the skill root:
    python3 tests/smoke_test.py

Exits non-zero on any assertion failure. Intended for a "does the plumbing
still work after I edited parse_page.py" sanity check, not exhaustive coverage.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).parent
SKILL_ROOT = HERE.parent
FIX = HERE / "fixtures"
PARSE = SKILL_ROOT / "scripts" / "parse_page.py"
RENDER = SKILL_ROOT / "scripts" / "render_preview.py"

TEST_USER = "test-user-001-alex-example"


def run(cmd, input_bytes=None, check=True):
    r = subprocess.run(cmd, capture_output=True, check=False)
    if check and r.returncode != 0:
        print(f"FAIL: {' '.join(str(x) for x in cmd)}\nstderr: {r.stderr.decode()}", file=sys.stderr)
        sys.exit(1)
    return r


def assert_eq(actual, expected, label):
    if actual != expected:
        print(f"  FAIL {label}: expected {expected!r}, got {actual!r}", file=sys.stderr)
        sys.exit(1)
    print(f"  OK   {label}")


def assert_true(cond, label):
    if not cond:
        print(f"  FAIL {label}", file=sys.stderr)
        sys.exit(1)
    print(f"  OK   {label}")


def test_sections_on_empty():
    print("[sections on empty-weekly.json]")
    r = run(["python3", str(PARSE), "sections",
            str(FIX / "empty-weekly.json"),
            "--user-id", TEST_USER,
            "--team-config", str(FIX / "team-platform.json")])
    out = json.loads(r.stdout)
    kinds = [s["kind"] for s in out["sections"]]
    assert_eq(out["team_name"], "Platform", "team_name propagated")
    assert_true("explicit_assignment_no_team_block" in kinds, "row 1 → no_team_block")
    assert_eq(kinds.count("team_only_row"), 2, "2 team-only rows (Challenges, Releases)")
    assert_eq(len(out["skipped_rows"]), 0, "no skipped rows on empty fixture")


def test_sections_on_filled():
    print("[sections on filled-weekly.json]")
    r = run(["python3", str(PARSE), "sections",
            str(FIX / "filled-weekly.json"),
            "--user-id", TEST_USER,
            "--team-config", str(FIX / "team-platform.json")])
    out = json.loads(r.stdout)
    kinds = [s["kind"] for s in out["sections"]]
    assert_true("explicit_assignment_with_team_block" in kinds,
                "row 1 → with_team_block (Platform block exists)")
    # Row targeting only the other user w/ no Platform block should NOT be a section.
    assert_eq(kinds.count("explicit_assignment_no_team_block"), 0,
              "other-team prompt row is not claimed")
    assert_eq(kinds.count("team_only_row"), 2, "2 team-only rows")
    assert_eq(len(out["skipped_rows"]), 1, "1 skipped row (other team's assignment)")


def test_dates():
    print("[dates]")
    r = run(["python3", str(PARSE), "dates",
            "--title", "Weekly Report, 01 Jun - 05 Jun 2026 (Platform BU)"])
    out = json.loads(r.stdout)
    assert_eq(out, {"start": "2026-06-01", "end": "2026-06-05"}, "date range parsed")

    # Unparseable title must exit non-zero.
    r = run(["python3", str(PARSE), "dates", "--title", "No date here"], check=False)
    assert_true(r.returncode != 0, "unparseable title → non-zero exit")


def test_build_patch_and_strip():
    print("[build-patch + strip-sentinels]")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        drafts = {
            "table[0]/tableRow[1]/tableCell[0]": {
                "kind": "new_team_block",
                "team_name": "Platform",
                "paragraphs": [
                    "API gateway migration – staging rollout clean (PLAT-1234).",
                    "CVE remediation – two resolved this week.",
                ],
            },
            "table[0]/tableRow[2]/tableCell[0]": {
                "kind": "team_only_row_contribution",
                "update_cell_path": "table[0]/tableRow[2]/tableCell[0]",
                "team_name": "Platform",
                "bullets": ["CI flakiness on gateway pipeline."],
            },
        }
        drafts_path = td / "drafts.json"
        drafts_path.write_text(json.dumps(drafts))

        r = run(["python3", str(PARSE), "build-patch",
                str(FIX / "empty-weekly.json"),
                "--drafts", str(drafts_path)])
        modified = json.loads(r.stdout)
        mod_path = td / "modified.json"
        mod_path.write_text(r.stdout.decode())

        # Count sentinels in the modified doc.
        def count_sentinels(n):
            c = 0
            if isinstance(n, dict):
                if (n.get("attrs") or {}).get("_skillAdded") is True:
                    c += 1
                for ch in n.get("content") or []:
                    c += count_sentinels(ch)
            return c

        sentinels_before = count_sentinels(modified)
        assert_true(sentinels_before >= 4, f"sentinels inserted (>=4, got {sentinels_before})")

        # Now strip and verify they're all gone.
        r = run(["python3", str(PARSE), "strip-sentinels", str(mod_path)])
        stripped = json.loads(r.stdout)
        assert_eq(count_sentinels(stripped), 0, "strip-sentinels removes all")

        # Content preserved through the strip.
        flat = json.dumps(stripped)
        assert_true("API gateway migration" in flat, "added content survives strip")
        assert_true("Platform" in flat, "team name survives strip")


def test_render_preview():
    print("[render_preview]")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        drafts = {
            "table[0]/tableRow[1]/tableCell[0]": {
                "kind": "new_team_block",
                "team_name": "Platform",
                "paragraphs": ["Rendered preview test paragraph."],
            }
        }
        drafts_path = td / "drafts.json"
        drafts_path.write_text(json.dumps(drafts))
        mod_path = td / "modified.json"
        r = run(["python3", str(PARSE), "build-patch",
                str(FIX / "empty-weekly.json"), "--drafts", str(drafts_path)])
        mod_path.write_text(r.stdout.decode())

        html_path = td / "preview.html"
        run(["python3", str(RENDER), str(mod_path),
            "--title", "Test Preview", "--out", str(html_path)])
        html = html_path.read_text()
        assert_true("skill-added" in html, "preview contains skill-added CSS class")
        assert_true("Rendered preview test paragraph" in html, "preview contains added text")
        assert_true("<table" in html, "preview renders the table")


def main():
    test_sections_on_empty()
    test_sections_on_filled()
    test_dates()
    test_build_patch_and_strip()
    test_render_preview()
    print("\nAll smoke tests passed.")


if __name__ == "__main__":
    main()
