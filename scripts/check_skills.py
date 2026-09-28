#!/usr/bin/env python3
"""Check every skill against the Neens MCP tool surface.

The skills tell an agent to call Neens tools with specific arguments. When Neens renames a tool or an
argument, a skill silently starts sending calls that fail. This script catches that:

  * every SKILL.md has valid frontmatter (name == directory, a description of at most 1024 chars)
  * every backticked tool-looking name is a real Neens tool
  * every JSON argument object in a skill uses only keys the nearby tool actually accepts

Tool schemas come from `scripts/tools.snapshot.json` by default. Pass `--url` to read them from a
live Neens instead, and `--write-snapshot` to refresh the committed snapshot from that instance:

    python3 scripts/check_skills.py
    NEENS_TOKEN=... python3 scripts/check_skills.py --url https://your-neens --write-snapshot

`NEENS_TOKEN` must be a credential that instance accepts on `/mcp`. app.neens.ai accepts only a
user sign-in token there (an `nk_live_` agent key gets a 401), so refresh against an instance that
takes a key, or pass a user token.

Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"
SNAPSHOT = ROOT / "scripts" / "tools.snapshot.json"

# Backticked snake_case words that are arguments, fields or values, not tools.
TOOL_SHAPED = re.compile(r"`([a-z]+(?:_[a-z0-9]+)+)`")
JSON_OBJECT = re.compile(r"\{[^{}]*\"[a-z_]+\"\s*:[^{}]*\}")
JSON_KEY = re.compile(r"\"([a-z_]+)\"\s*:")
# Keys that live inside nested argument values (e.g. a model-sweep arm), not at the top level.
NESTED_KEYS = {"label", "agent_connection_id"}


def fetch_tools(url: str, token: str | None) -> list[dict]:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
    req = urllib.request.Request(url.rstrip("/") + "/mcp", data=body, method="POST")
    req.add_header("content-type", "application/json")
    if token:
        req.add_header("authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)["result"]["tools"]


def frontmatter(text: str) -> dict[str, str]:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}
    out: dict[str, str] = {}
    key = None
    for line in m.group(1).splitlines():
        kv = re.match(r"^([a-z_]+):\s*(.*)$", line)
        if kv:
            key = kv.group(1)
            out[key] = "" if kv.group(2) in (">", "|") else kv.group(2)
        elif key:
            out[key] = (out[key] + " " + line.strip()).strip()
    return out


def blocks(text: str) -> list[str]:
    """Paragraphs, list items and fenced code blocks, in order."""
    parts: list[str] = []
    for chunk in re.split(r"(```.*?```)", text, flags=re.S):
        if chunk.startswith("```"):
            parts.append(chunk)
        else:
            parts.extend(p for p in re.split(r"\n\s*\n|\n(?=\s*(?:[-*]|\d+\.)\s)", chunk) if p.strip())
    return parts


def check(tools: list[dict]) -> list[str]:
    schema = {t["name"]: set(t.get("inputSchema", {}).get("properties", {})) for t in tools}
    all_args = set().union(*schema.values())
    problems: list[str] = []
    for skill_md in sorted(SKILLS.glob("*/SKILL.md")):
        rel = skill_md.relative_to(ROOT)
        text = skill_md.read_text()
        fm = frontmatter(text)
        if fm.get("name") != skill_md.parent.name:
            problems.append(f"{rel}: frontmatter name {fm.get('name')!r} != directory {skill_md.parent.name!r}")
        desc = fm.get("description", "")
        if not desc or len(desc) > 1024:
            problems.append(f"{rel}: description missing or longer than 1024 chars ({len(desc)})")

        for name in sorted(set(TOOL_SHAPED.findall(text))):
            if name not in schema and name not in all_args and name not in FIELDS:
                problems.append(f"{rel}: `{name}` is not a Neens tool or argument")

        previous: list[str] = []
        for block in blocks(text):
            here = [n for n in TOOL_SHAPED.findall(block) if n in schema]
            nearby = here or previous
            for obj in JSON_OBJECT.findall(block):
                keys = set(JSON_KEY.findall(obj)) - NESTED_KEYS
                if not nearby or not keys:
                    continue
                allowed = set().union(*(schema[n] for n in nearby))
                bad = keys - allowed
                # A JSON object that shares no key with the nearby tools is a response or a
                # judge output, not arguments; only flag partial mismatches.
                if bad and keys & allowed:
                    problems.append(f"{rel}: {sorted(bad)} not accepted by {sorted(set(nearby))}: {obj[:80]}")
            if here:
                previous = here
    return problems


# Response fields, enum values and example names the skills quote on purpose.
FIELDS = {
    # enum values and response fields quoted from tool replies
    "needs_grounding", "working_as_intended", "on_new_trace", "input_json", "openai_chat",
    "prod_window", "preprod_run", "completed_with_regressions", "primary_score",
    "failure_set", "is_gold", "required_data", "prompt_template", "baseline_kind",
    # standard OpenTelemetry / environment names used by instrument-agent
    "force_flush", "tracer_provider", "final_answer", "final_output",
    # an example tool name from the user's own agent
    "lookup_order",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", help="Neens base URL to read tools/list from (default: the snapshot)")
    ap.add_argument("--write-snapshot", action="store_true", help="save the fetched tools as the snapshot")
    args = ap.parse_args()

    if args.url:
        tools = fetch_tools(args.url, os.environ.get("NEENS_TOKEN"))
        if args.write_snapshot:
            SNAPSHOT.write_text(json.dumps(sorted(tools, key=lambda t: t["name"]), indent=1) + "\n")
            print(f"wrote {len(tools)} tools to {SNAPSHOT.relative_to(ROOT)}")
    else:
        tools = json.loads(SNAPSHOT.read_text())

    problems = check(tools)
    for p in problems:
        print(p)
    count = len(list(SKILLS.glob("*/SKILL.md")))
    print(f"{count} skills checked against {len(tools)} tools: {'OK' if not problems else f'{len(problems)} problem(s)'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
