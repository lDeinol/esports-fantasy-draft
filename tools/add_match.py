#!/usr/bin/env python3
"""
add_match.py — Quick CLI tool to add a match to data/matches.json

Looks up tournaments from data/tournaments.json and players from
data/players.json so you can pick by name instead of typing IDs from memory.

Usage:
    python3 add_match.py
"""

import json
import os
import sys
import argparse
import re

VALID_STATUSES = ["upcoming", "live", "completed"]
VALID_FORMATS  = ["BO1", "BO3", "BO5"]


def load_json(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
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


def prompt_date(label, required=True):
    while True:
        val = prompt(f"{label} (YYYY-MM-DD)", required=required)
        if val == "" and not required:
            return None
        if re.match(r"^\d{4}-\d{2}-\d{2}$", val):
            return val
        print("  Please use the format YYYY-MM-DD")


def prompt_choice(label, options, required=True):
    print(f"  Options: {', '.join(options)}")
    while True:
        val = prompt(label, required=required)
        match = next((o for o in options if o.lower() == val.lower()), None)
        if match:
            return match
        if not required and val == "":
            return None
        print(f"  Must be one of: {', '.join(options)}")


def pick_tournament(tournaments):
    if not tournaments:
        print("No tournaments found. Add one first with add_tournament.py")
        sys.exit(1)

    print("\nAvailable tournaments:")
    for i, t in enumerate(tournaments, 1):
        print(f"  {i}. {t['name']}  [{t['status']}]  (id: {t['id']})")

    while True:
        val = prompt("\nSelect tournament number")
        try:
            idx = int(val) - 1
            if 0 <= idx < len(tournaments):
                return tournaments[idx]["id"]
        except ValueError:
            pass
        print("  Enter a valid number from the list.")


def find_player(players, query):
    query = query.strip().lower()
    matches = [p for p in players if p["id"].lower() == query or p["name"].lower() == query]
    if matches:
        return matches[0]
    # Partial match fallback
    partial = [p for p in players if query in p["name"].lower()]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        print(f"  Multiple matches for '{query}':")
        for p in partial:
            print(f"    - {p['name']} ({p['team']})")
        return None
    return None


def prompt_player_stats(players, team_name):
    print(f"\n  --- Player stats for {team_name} ---")
    print("  (Enter player name/ID, or leave blank to stop adding players for this team)")
    stats_list = []
    while True:
        query = prompt("  Player name or ID", required=False)
        if not query:
            break
        player = find_player(players, query)
        if not player:
            print(f"  No player found matching '{query}'. Add them with add_player.py first, or try again.")
            continue

        print(f"  Found: {player['name']} ({player['team']}) — entering match stats:")
        rating = prompt_float("    Rating")
        kd     = prompt_float("    K/D")
        acs    = prompt_float("    ACS")
        adr    = prompt_float("    ADR")
        kpr    = prompt_float("    KPR")
        cl     = prompt_float("    CL%")

        stats_list.append({
            "playerId": player["id"],
            "team": team_name,
            "rating": rating,
            "kd": kd,
            "acs": acs,
            "adr": adr,
            "kpr": kpr,
            "cl": cl,
        })
        print(f"  ✓ Added stats for {player['name']}\n")

    return stats_list


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--matches-file",     default="data/matches.json")
    parser.add_argument("--tournaments-file", default="data/tournaments.json")
    parser.add_argument("--players-file",     default="data/players.json")
    args = parser.parse_args()

    matches     = load_json(args.matches_file)
    tournaments = load_json(args.tournaments_file)
    players     = load_json(args.players_file)
    existing_ids = {m["id"] for m in matches}

    print(f"\n=== Add Match ({len(matches)} matches currently in {args.matches_file}) ===")

    while True:
        tournament_id = pick_tournament(tournaments)

        next_num = len(matches) + 1
        default_id = f"m{next_num:03d}"
        match_id = prompt("\nMatch ID (unique)", default=default_id)
        if match_id in existing_ids:
            overwrite = prompt(f"ID '{match_id}' already exists. Overwrite? (y/n)", default="n")
            if overwrite.lower() != "y":
                print("Skipped.\n")
                continue
            matches = [m for m in matches if m["id"] != match_id]

        team1  = prompt("Team 1 name")
        team2  = prompt("Team 2 name")
        fmt    = prompt_choice("Format", VALID_FORMATS, required=True)
        date   = prompt_date("Match date")
        status = prompt_choice("Status", VALID_STATUSES, required=True)

        score, winner, player_stats = None, None, []

        if status == "completed":
            score = prompt(f"Score (e.g. 2-1, {team1} first)")
            winner = prompt_choice("Winner", [team1, team2], required=True)

            print("\nNow enter player stats for this match.")
            team1_stats = prompt_player_stats(players, team1)
            team2_stats = prompt_player_stats(players, team2)
            player_stats = team1_stats + team2_stats
        else:
            print(f"  Status is '{status}' — skipping score/stats (add them later once the match is complete).")

        new_match = {
            "id": match_id,
            "tournamentId": tournament_id,
            "team1": team1,
            "team2": team2,
            "score": score,
            "winner": winner,
            "format": fmt,
            "date": date,
            "status": status,
            "playerStats": player_stats,
        }

        matches.append(new_match)
        existing_ids.add(match_id)
        save_json(args.matches_file, matches)
        print(f"\n✓ Added match '{team1} vs {team2}' ({match_id}). Total matches: {len(matches)}\n")

        again = prompt("Add another match? (y/n)", default="y")
        if again.lower() != "y":
            break

    print(f"\nDone. {args.matches_file} now has {len(matches)} matches.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCancelled.")
        sys.exit(0)
