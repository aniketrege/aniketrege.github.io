#!/usr/bin/env python3
"""
Fetch citation statistics from Google Scholar profile and update _data/citations.yml
"""

import html
import os
from pathlib import Path
import re
import sys
import urllib.request
import yaml


def normalize_title(title: str) -> str:
    """Normalize string for fuzzy title matching."""
    cleaned = re.sub(r"[{}\"']", "", title)
    cleaned = re.sub(r"[^a-zA-Z0-9]+", " ", cleaned).lower().strip()
    return cleaned


def parse_bib_file(bib_path: str):
    """Parse papers.bib into a list of (bib_key, title, google_scholar_id)."""
    with open(bib_path, "r", encoding="utf-8") as f:
        content = f.read()

    entries = []
    # Match entry header @type{key,
    entry_blocks = re.split(r"\n@(\w+)\s*\{\s*([^,]+),", content)
    # entry_blocks has: [preamble, type1, key1, body1, type2, key2, body2, ...]
    for i in range(1, len(entry_blocks), 3):
        bib_key = entry_blocks[i + 1].strip()
        body = entry_blocks[i + 2]

        title_m = re.search(r'title\s*=\s*[\{"](.*?)[}"]', body, re.DOTALL)
        gs_id_m = re.search(r'google_scholar_id\s*=\s*[\{"](.*?)[}"]', body)

        title = title_m.group(1).replace("\n", " ").strip() if title_m else ""
        gs_id = gs_id_m.group(1).strip() if gs_id_m else None

        entries.append({
            "key": bib_key,
            "title": title,
            "norm_title": normalize_title(title),
            "gs_id": gs_id,
        })
    return entries


def fetch_scholar_data(user_id: str):
    """Scrape the Google Scholar public profile for user_id."""
    url = f"https://scholar.google.com/citations?user={user_id}&hl=en&cstart=0&pagesize=100"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        page_html = resp.read().decode("utf-8")

    # Extract overall metrics: Total, h-index, i10-index
    # The table has columns: All, Since 201x
    # First row: Citations, Second row: h-index, Third row: i10-index
    metrics = re.findall(r'<td class="gsc_rsb_std">(\d+)</td>', page_html)
    total_citations = int(metrics[0]) if len(metrics) >= 1 else 0
    h_index = int(metrics[2]) if len(metrics) >= 3 else 0
    i10_index = int(metrics[4]) if len(metrics) >= 5 else 0

    # Extract paper rows
    rows = re.findall(r'<tr class="gsc_a_tr">(.*?)</tr>', page_html, re.DOTALL)
    papers = []
    for row in rows:
        title_m = re.search(r'class="gsc_a_at"[^>]*>([^<]+)</a>', row)
        cid_m = re.search(r'citation_for_view=[^:]+:([^"&]+)', row)
        cites_m = re.search(r'class="gsc_a_ac[^"]*"[^>]*>([^<]*)</a>', row)

        title = html.unescape(title_m.group(1).strip()) if title_m else ""
        cid = cid_m.group(1).strip() if cid_m else ""
        cites_raw = cites_m.group(1).strip() if cites_m else "0"
        cites = int(cites_raw) if cites_raw.isdigit() else 0

        papers.append({
            "title": title,
            "norm_title": normalize_title(title),
            "cid": cid,
            "citations": cites,
        })

    return {
        "total_citations": total_citations,
        "h_index": h_index,
        "i10_index": i10_index,
        "papers": papers,
    }


def match_and_build_yaml(bib_entries, scholar_data, user_id):
    """Match bib entries against Google Scholar records and build YAML data."""
    scholar_papers = scholar_data["papers"]
    citation_map = {}
    scholar_id_map = {}

    for entry in bib_entries:
        match = None
        # 1. Match by explicit google_scholar_id if present
        if entry["gs_id"]:
            for sp in scholar_papers:
                if sp["cid"] == entry["gs_id"]:
                    match = sp
                    break

        # 2. Fuzzy title matching
        if not match:
            for sp in scholar_papers:
                if (
                    entry["norm_title"] == sp["norm_title"]
                    or entry["norm_title"].startswith(sp["norm_title"])
                    or sp["norm_title"].startswith(entry["norm_title"])
                ):
                    match = sp
                    break

        # 3. Partial substring matching for long titles
        if not match and len(entry["norm_title"]) > 15:
            prefix = entry["norm_title"][:25]
            for sp in scholar_papers:
                if prefix in sp["norm_title"]:
                    match = sp
                    break

        if match:
            citation_map[entry["key"]] = match["citations"]
            scholar_id_map[entry["key"]] = match["cid"]

    output_data = {
        "scholar_userid": user_id,
        "total_citations": scholar_data["total_citations"],
        "h_index": scholar_data["h_index"],
        "i10_index": scholar_data["i10_index"],
        "papers": citation_map,
        "scholar_ids": scholar_id_map,
    }
    return output_data


def main():
    root_dir = Path(__file__).resolve().parent.parent
    bib_path = root_dir / "_bibliography" / "papers.bib"
    output_path = root_dir / "_data" / "citations.yml"
    config_path = root_dir / "_config.yml"

    # Read scholar_userid from _config.yml
    user_id = "qdsfqI4AAAAJ"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
            user_id = cfg.get("scholar_userid", user_id)

    print(f"Fetching Google Scholar data for user ID: {user_id}...")
    try:
        scholar_data = fetch_scholar_data(user_id)
    except Exception as e:
        print(f"Warning: Failed to fetch data from Google Scholar: {e}", file=sys.stderr)
        print("Existing citations file will remain untouched to prevent breaking the build.")
        sys.exit(0)

    # Sanity checks: ensure we received valid, non-empty data
    if not scholar_data.get("papers") or scholar_data.get("total_citations", 0) <= 0:
        print(
            "Warning: Received empty or abnormal response from Google Scholar. "
            "Skipping update to prevent overwriting existing citation data.",
            file=sys.stderr,
        )
        sys.exit(0)

    # If an existing citations.yml exists, ensure the new total count didn't drop suspiciously (e.g. rate limit / partial page)
    if output_path.exists():
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                old_data = yaml.safe_load(f) or {}
                old_total = old_data.get("total_citations", 0)
                if scholar_data["total_citations"] < old_total:
                    print(
                        f"Warning: Fetched citations ({scholar_data['total_citations']}) "
                        f"is lower than existing ({old_total}). "
                        "Suspected partial fetch or rate-limit. Keeping existing file.",
                        file=sys.stderr,
                    )
                    sys.exit(0)
        except Exception as e:
            print(f"Notice: Could not read existing {output_path}: {e}")

    print(
        f"Fetched profile: {scholar_data['total_citations']} total citations, "
        f"h-index: {scholar_data['h_index']}, {len(scholar_data['papers'])} papers found."
    )

    bib_entries = parse_bib_file(str(bib_path))
    output_data = match_and_build_yaml(bib_entries, scholar_data, user_id)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(output_data, f, sort_keys=False, default_flow_style=False)

    print(f"Updated {output_path} successfully!")
    print("\nMatched Papers:")
    for key, count in output_data["papers"].items():
        print(f"  - {key}: {count} citations (cid: {output_data['scholar_ids'].get(key)})")


if __name__ == "__main__":
    main()
