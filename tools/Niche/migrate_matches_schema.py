#!/usr/bin/env python3
"""
migrate_matches_schema.py — One-off cleanup for an existing matches.json:
    - Drops the redundant "vlrId" field (identical to "id" in every
      match written by vlr_scrape.py / scrape_tournament.py).
    - Reorders each match's keys so "series" sits right after
      "tournamentId", matching the current scraper output.
    - Leaves matches that don't yet have a "series" field alone aside
      from dropping vlrId (run backfill_series.py first if you want
      series filled in for older matches).

Safe to run more than once — it's idempotent.

Usage:
    python3 migrate_matches_schema.py                  # data/matches.json
    python3 migrate_matches_schema.py --matches-file data/matches.json
"""

import argparse
import vlr_scrape as vs

FIELD_ORDER = [
    "id", "tournamentId", "series", "team1", "team2", "score",
    "winner", "format", "date", "status", "playerStats",
]


def reshape(match):
    match.pop("vlrId", None)
    # Preserve any fields not in FIELD_ORDER (e.g. future additions) by
    # appending them after the known ones, in their original order.
    ordered = {k: match[k] for k in FIELD_ORDER if k in match}
    extras = {k: v for k, v in match.items() if k not in FIELD_ORDER}
    ordered.update(extras)
    return ordered


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--matches-file", default="data/matches.json")
    args = parser.parse_args()

    matches = vs.load_json(args.matches_file)
    matches = [reshape(m) for m in matches]
    vs.save_json(args.matches_file, matches)
    print(f"Migrated {len(matches)} match(es) in {args.matches_file}.")


if __name__ == "__main__":
    main()
