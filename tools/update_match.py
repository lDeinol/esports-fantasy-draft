#!/usr/bin/env python3
"""
update_match.py — Mark an upcoming/live match as completed and fill in stats.

This is the typical workflow: you add a match as "upcoming" ahead of time
with add_match.py, then once it's played, run this script to fill in the
score, winner, and player stats.

Usage:
    python3 update_match.py
"""

import json
import os
import sys
import argparse

VALID_STATUSES = ["upcoming", "live", "completed"]


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


def prompt_int(label, required=True):
    while True:
        val = prompt(label, required=required)
        if val == "" and not required:
            return None
        try:
            return int(val)
        except ValueError:
            print("  Please enter a whole number.")


def prompt_choice(label, options, required=True):
    print(f"  Options: {', '.join(options)}")
    while True:
        val = prompt(label, required=required)
        match = next((o for o in options if o.lower() == val.lower()), None)
        if match:
            return match
        print(f"  Must be one of: {', '.join(options)}")


def find_player(players, query):
    query = query.strip().lower()
    matches = [p for p in players if p["id"].lower() == query or p["name"].lower() == query]
    if matches:
        return matches[0]
    partial = [p for p in players if query in p["name"].lower()]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        print(f"  Multiple matches for '{query}':")
        for p in partial:
            print(f"    - {p['name']} ({p['team']})")
        return None
    return None


def prompt_player_stats(players, team_name, rounds):
    print(f"\n  --- Player stats for {team_name} ---")
    print("  (Enter player name/ID, or leave blank to stop)")
    stats_list = []
    while True:
        query = prompt("  Player name or ID", required=False)
        if not query:
            break
        player = find_player(players, query)
        if not player:
            print(f"  No player found matching '{query}'.")
            continue

        print(f"  Found: {player['name']} ({player['team']}) — entering match stats:")
        rating = prompt_float("    Rating")
        acs    = prompt_float("    ACS")
        kills  = prompt_int("    Kills")
        deaths = prompt_int("    Deaths")
        adr    = prompt_float("    ADR")

        kd  = round(kills / deaths, 2) if deaths > 0 else kills
        kpr = round(kills / rounds, 2) if rounds > 0 else 0

        print(f"    → K/D: {kd}  KPR: {kpr}")

        stats_list.append({
            "playerId": player["id"],
            "team": team_name,
            "rating": rating,
            "kd": kd,
            "acs": acs,
            "adr": adr,
            "kpr": kpr,
        })
        print(f"  ✓ Added stats for {player['name']}\n")

    return stats_list


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--matches-file", default="data/matches.json")
    parser.add_argument("--players-file", default="data/players.json")
    args = parser.parse_args()

    matches = load_json(args.matches_file)
    players = load_json(args.players_file)

    if not matches:
        print("No matches found.")
        sys.exit(1)

    # Show non-completed matches first since those are the likely targets
    pending = [m for m in matches if m["status"] != "completed"]
    show_list = pending if pending else matches

    print(f"\n=== Update Match ===")
    print("\nMatches:" if not pending else "\nUpcoming / live matches:")
    for i, m in enumerate(show_list, 1):
        print(f"  {i}. {m['team1']} vs {m['team2']}  [{m['status']}]  (id: {m['id']}, date: {m['date']})")

    while True:
        val = prompt("\nSelect match number to update")
        try:
            idx = int(val) - 1
            if 0 <= idx < len(show_list):
                target = show_list[idx]
                break
        except ValueError:
            pass
        print("  Enter a valid number from the list.")

    print(f"\nUpdating: {target['team1']} vs {target['team2']} ({target['id']})")

    new_status = prompt_choice("New status", VALID_STATUSES, required=True)
    target["status"] = new_status

    if new_status == "completed":
        score  = prompt(f"Score (e.g. 2-1, {target['team1']} first)")
        winner = prompt_choice("Winner", [target["team1"], target["team2"]], required=True)
        rounds = prompt_int("Total rounds played")
        target["score"]  = score
        target["winner"] = winner

        replace_stats = "y"
        if target.get("playerStats"):
            replace_stats = prompt(f"This match already has {len(target['playerStats'])} player stat lines. Replace them? (y/n)", default="n")

        if replace_stats.lower() == "y":
            print("\nEnter player stats for this match.")
            team1_stats = prompt_player_stats(players, target["team1"], rounds)
            team2_stats = prompt_player_stats(players, target["team2"], rounds)
            target["playerStats"] = team1_stats + team2_stats

    # Write back
    for i, m in enumerate(matches):
        if m["id"] == target["id"]:
            matches[i] = target
            break

    save_json(args.matches_file, matches)
    print(f"\n✓ Updated match '{target['team1']} vs {target['team2']}' → status: {target['status']}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCancelled.")
        sys.exit(0)
