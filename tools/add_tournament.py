#!/usr/bin/env python3
"""
add_tournament.py — Quick CLI tool to add a tournament to data/tournaments.json

Usage:
    python3 add_tournament.py
"""

import json
import os
import sys
import argparse
import re

VALID_STATUSES = ["upcoming", "ongoing", "completed"]


def load_tournaments(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_tournaments(path, tournaments):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(tournaments, f, indent=2, ensure_ascii=False)
        f.write("\n")


def prompt(label, required=True, default=None):
    while True:
        suffix = f" [{default}]" if default else ""
        val = input(f"{label}{suffix}: ").strip()
        if not val and default is not None:
            return default
        if not val and required:
            print("  This field is required.")
            continue
        return val


def prompt_date(label, required=True):
    while True:
        val = prompt(f"{label} (YYYY-MM-DD)", required=required)
        if val == "" and not required:
            return None
        if re.match(r"^\d{4}-\d{2}-\d{2}$", val):
            return val
        print("  Please use the format YYYY-MM-DD, e.g. 2025-03-14")


def prompt_status():
    print(f"  Status options: {', '.join(VALID_STATUSES)}")
    while True:
        val = prompt("Status").lower()
        if val in VALID_STATUSES:
            return val
        print(f"  Must be one of: {', '.join(VALID_STATUSES)}")


def prompt_list(label):
    raw = prompt(f"{label} (comma-separated)", required=False)
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="data/tournaments.json", help="Path to tournaments.json")
    args = parser.parse_args()

    path = args.file
    tournaments = load_tournaments(path)
    existing_ids = {t["id"] for t in tournaments}

    print(f"\n=== Add Tournament ({len(tournaments)} tournaments currently in {path}) ===\n")

    while True:
        name = prompt("Tournament name")
        default_id = slugify(name)

        t_id = prompt("Tournament ID (unique, used by matches.json to link)", default=default_id)
        if t_id in existing_ids:
            overwrite = prompt(f"ID '{t_id}' already exists. Overwrite? (y/n)", default="n")
            if overwrite.lower() != "y":
                print("Skipped.\n")
                continue
            tournaments = [t for t in tournaments if t["id"] != t_id]

        region     = prompt("Region (Americas / EMEA / Pacific / China / International)")
        status     = prompt_status()
        start_date = prompt_date("Start date")
        end_date   = prompt_date("End date")
        prize_pool = prompt("Prize pool (e.g. $250,000)", required=False, default="TBD")
        teams      = prompt_list("Participating teams")
        logo_color = prompt("Accent color hex (e.g. #00e5ff)", required=False, default="#00e5ff")

        new_tournament = {
            "id": t_id,
            "name": name,
            "region": region,
            "status": status,
            "startDate": start_date,
            "endDate": end_date,
            "prizePool": prize_pool,
            "teams": teams,
            "logoColor": logo_color,
        }

        tournaments.append(new_tournament)
        existing_ids.add(t_id)
        save_tournaments(path, tournaments)
        print(f"\n✓ Added '{name}' ({t_id}). Total tournaments: {len(tournaments)}\n")
        print(f"  Remember this ID when adding matches for this tournament: {t_id}\n")

        again = prompt("Add another tournament? (y/n)", default="y")
        if again.lower() != "y":
            break

    print(f"\nDone. {path} now has {len(tournaments)} tournaments.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCancelled.")
        sys.exit(0)
