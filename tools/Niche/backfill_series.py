#!/usr/bin/env python3
"""
backfill_series.py — One-off helper to add the new "series" field
(e.g. "Playoffs: Upper Final") to matches already saved in matches.json
from before vlr_scrape.py captured it.

Re-fetches each match's page just to pull .match-header-event-series —
does NOT touch scores/stats/status, so it's safe to run over a whole
existing matches.json without disturbing completed match data.

Usage:
    python3 backfill_series.py                     # all matches missing "series"
    python3 backfill_series.py --matches-file data/matches.json
"""

import argparse
import sys
import time

import vlr_scrape as vs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--matches-file", default="data/matches.json")
    parser.add_argument("--delay", type=float, default=1.5)
    args = parser.parse_args()

    matches = vs.load_json(args.matches_file)
    todo = [m for m in matches if "series" not in m and m.get("vlrId")]

    if not todo:
        print("Nothing to backfill — every match already has a 'series' field.")
        sys.exit(0)

    print(f"Backfilling 'series' for {len(todo)} match(es)...")
    for i, m in enumerate(todo, 1):
        url = f"https://www.vlr.gg/{m['vlrId']}"
        html = vs.fetch_page(url)
        if not html:
            print(f"  [{i}/{len(todo)}] {m['id']}: fetch failed, skipped")
            continue
        data = vs.parse_match(html, m["vlrId"])
        m["series"] = data["series"]
        print(f"  [{i}/{len(todo)}] {m['id']}: series = {data['series'] or '(none found)'}")
        vs.save_json(args.matches_file, matches)
        if i < len(todo):
            time.sleep(args.delay)

    print(f"\nDone. Saved to {args.matches_file}.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCancelled.")
        sys.exit(0)
