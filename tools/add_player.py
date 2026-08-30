#!/usr/bin/env python3
"""
add_player.py — Quick CLI tool to add a player to data/players.json

Usage:
    python3 add_player.py

Run from the project root (where data/players.json lives), or pass a path:
    python3 add_player.py --file path/to/players.json
"""

import json
import os
import sys
import argparse

VALID_ROLES = ["Duelist", "Controller", "Initiator", "Sentinel", "Operator", "Flex"]


def load_players(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_players(path, players):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(players, f, indent=2, ensure_ascii=False)
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


def prompt_float(label, required=True):
    while True:
        val = prompt(label, required=required)
        if val == "" and not required:
            return None
        try:
            return float(val)
        except ValueError:
            print("  Please enter a valid number.")


def prompt_role():
    print(f"  Roles: {', '.join(VALID_ROLES)}")
    while True:
        val = prompt("Role")
        # Allow case-insensitive match
        match = next((r for r in VALID_ROLES if r.lower() == val.lower()), None)
        if match:
            return match
        print(f"  '{val}' isn't a standard role, but it'll still be saved as entered.")
        return val


def slugify(name):
    return name.strip().replace(" ", "_")


def add_one_player(players, existing_ids, name, team, region):
    """Given name/team, prompt for Role -> Stats, save, and return updated players/existing_ids."""
    player_id = slugify(name)

    if player_id in existing_ids:
        overwrite = prompt(f"ID '{player_id}' already exists. Overwrite? (y/n)", default="n")
        if overwrite.lower() != "y":
            print("Skipped.\n")
            return players, existing_ids

    role = prompt_role()

    print("\n  Enter season average stats:")
    rating = prompt_float("  Rating")
    acs    = prompt_float("  ACS")
    kd     = prompt_float("  K/D")
    adr    = prompt_float("  ADR")
    kpr    = prompt_float("  KPR")

    new_player = {
        "id": player_id,
        "name": name,
        "team": team,
        "role": role,
        "region": region,
        "status": "active",
        "stats": {
            "rating": rating,
            "acs": acs,
            "kd": kd,
            "adr": adr,
            "kpr": kpr,
        },
    }

    players = [p for p in players if p["id"] != player_id]
    players.append(new_player)
    existing_ids.add(player_id)
    return players, existing_ids


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="data/players.json", help="Path to players.json")
    args = parser.parse_args()

    path = args.file
    players = load_players(path)
    existing_ids = {p["id"] for p in players}

    print(f"\n=== Add Player ({len(players)} players currently in {path}) ===\n")

    region = prompt("Region (Americas / EMEA / Pacific / China)")

    mode = ""
    while mode.lower() not in ("bulk", "individual"):
        mode = prompt("Mode — Bulk or Individual?")

    if mode.lower() == "individual":
        while True:
            name = prompt("\nPlayer name (in-game handle)")
            team = prompt("Team")
            players, existing_ids = add_one_player(players, existing_ids, name, team, region)
            save_players(path, players)
            print(f"\n✓ Total players: {len(players)}\n")

            again = prompt("Add another player? (y/n)", default="y")
            if again.lower() != "y":
                break

    else:  # bulk
        while True:
            team = prompt("\nTeam")
            count = 0
            while count <= 0:
                try:
                    count = int(prompt(f"# of players on {team}"))
                except ValueError:
                    print("  Please enter a whole number.")
                    count = 0

            for i in range(count):
                print(f"\n  -- Player {i + 1} of {count} ({team}) --")
                name = prompt("Player name (in-game handle)")
                players, existing_ids = add_one_player(players, existing_ids, name, team, region)
                save_players(path, players)
                print(f"  ✓ Total players: {len(players)}")

            another_team = prompt("\nAnother team? (y/n)", default="y")
            if another_team.lower() != "y":
                break

    print(f"\nDone. {path} now has {len(players)} players.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCancelled.")
        sys.exit(0)
