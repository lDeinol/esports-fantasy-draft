#!/usr/bin/env python3
"""
scrape_tournament.py — Find the ongoing tournament in tournaments.json,
pull the full match list for that tournament from VLR.gg, and scrape
any matches that aren't already in matches.json.

How it works:
    1. Reads tournaments.json, finds the tournament with status == "ongoing".
    2. Fetches https://www.vlr.gg/event/matches/{tournament_id}/?series_id=all
    3. Scans every element with class "wf-card" for <a href="/12345/..."> links
       and pulls out the numeric match ID (first path segment).
    4. Skips any match ID already present in matches.json (matched via "vlrId").
    5. Skips matches VLR still marks as not-yet-played ("Upcoming").
    6. For every new, completed match, reuses vlr_scrape.py's own
       fetch_page() / parse_match() / match_player_ids() logic to scrape
       it and append it to matches.json — same schema as vlr_scrape.py
       produces, with tournamentId set to the tournament's numeric VLR id
       (matches the "id" field in tournaments.json).

Usage:
    python3 scrape_tournament.py
    python3 scrape_tournament.py --tournament-id 2952
    python3 scrape_tournament.py --include-upcoming

Run from the same folder as vlr_scrape.py (it's imported here for parsing),
and with the same directory layout it expects (data/tournaments.json,
data/matches.json, data/players.json by default).

Requirements:
    pip install requests beautifulsoup4

Note: as of the latest vlr_scrape.py, both team-name resolution and total
rounds are auto-detected — parse_match() no longer prompts for either in
the normal case. It only falls back to the interactive "Enter Total
Rounds:" prompt on the rare match where VLR's per-map score markup can't
be read. Pass --unattended to skip those matches instead of blocking on
input (useful for cron/unattended runs) — they'll just be picked up
again next time you run this without --unattended.
"""

import argparse
import builtins
import re
import sys
import time

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("Missing dependencies. Run: pip install requests beautifulsoup4")
    sys.exit(1)

import vlr_scrape as vs  # reuse fetch_page, parse_match, match_player_ids, load/save json


class RoundsPromptBlocked(Exception):
    """Raised in --unattended mode when parse_match() would otherwise
    block on the manual 'Enter Total Rounds:' input()."""


def _disabled_input(prompt=""):
    raise RoundsPromptBlocked(prompt)


# ── Find the ongoing tournament(s) ──────────────────────────
def find_ongoing_tournaments(tournaments):
    return [t for t in tournaments if t.get("status") == "ongoing"]


def pick_tournament(tournaments):
    if len(tournaments) == 1:
        return tournaments[0]
    print("\nMultiple ongoing tournaments found:")
    for i, t in enumerate(tournaments, 1):
        print(f"  {i}. {t['name']} (id={t['id']})")
    while True:
        val = input("Select tournament number: ").strip()
        try:
            idx = int(val) - 1
            if 0 <= idx < len(tournaments):
                return tournaments[idx]
        except ValueError:
            pass
        print("  Enter a valid number.")


# ── Scrape the event's match list page ──────────────────────
def get_event_matches_url(tournament_id):
    return f"https://www.vlr.gg/event/matches/{tournament_id}/?series_id=all"


def extract_match_ids(html):
    """
    Parse the VLR event matches page.
    Returns a list of (match_id, is_completed) tuples, in page order,
    deduplicated by match_id.
    """
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    results = []

    for card in soup.select(".wf-card"):
        for a in card.select("a[href]"):
            href = a.get("href", "")
            m = re.match(r"^/(\d+)/", href)
            if not m:
                continue
            match_id = m.group(1)
            if match_id in seen:
                continue
            seen.add(match_id)

            # VLR match-list links usually contain a status label
            # ("Completed", "LIVE", or a countdown for upcoming matches).
            status_el = a.select_one(".ml-status")
            status_text = (status_el.get_text(strip=True) if status_el
                            else a.get_text(" ", strip=True))
            is_completed = "completed" in status_text.lower()

            results.append((match_id, is_completed))

    return results


# ── Scrape a single match into matches.json ─────────────────
def scrape_match(vlr_id, tournament_id, players_data, matches, matches_file, unattended=False):
    url = f"https://www.vlr.gg/{vlr_id}"
    html = vs.fetch_page(url)
    if not html:
        print(f"  ✗ Could not fetch match {vlr_id}, skipping.")
        return False, []

    if unattended:
        original_input = builtins.input
        builtins.input = _disabled_input
        try:
            data = vs.parse_match(html, vlr_id)
        except RoundsPromptBlocked:
            print(f"  ⚠ Could not auto-detect total rounds for match {vlr_id}; "
                  f"skipping in --unattended mode (run again without it to enter manually).")
            return False, []
        finally:
            builtins.input = original_input
    else:
        data = vs.parse_match(html, vlr_id)

    print(f"\n  ✓ Parsed match: {data['teams'][0]} vs {data['teams'][1]}")
    print(f"    Score:  {data['score'] or 'N/A'}   Winner: {data['winner'] or 'N/A'}")
    print(f"    Date:   {data['date'] or 'unknown'}   Format: {data['format']}")

    unmatched_names = vs.match_player_ids(data["playerStats"], players_data)
    unmatched_context = []
    if unmatched_names:
        print(f"    ⚠ {len(unmatched_names)} unmatched player(s): {', '.join(unmatched_names)}")
        match_label = f"{data['teams'][0]} vs {data['teams'][1]}"
        for p in data["playerStats"]:
            if p["playerName"] in unmatched_names:
                unmatched_context.append({
                    "name":  p["playerName"],
                    "team":  p["team"],
                    "match": match_label,
                })

    status = vs.resolve_status(data["date"], bool(data["score"]))

    clean_stats = []
    if status != "upcoming":
        for p in data["playerStats"]:
            clean_stats.append({
                "playerId": p["playerId"],
                "team":     p["team"],
                "rating":   p["rating"],
                "kd":       p["kd"],
                "acs":      p["acs"],
                "adr":      p["adr"],
                "kpr":      p["kpr"],
            })

    match_id = vlr_id
    new_match = {
        "id":           match_id,
        "tournamentId": tournament_id,
        "team1":        data["teams"][0],
        "team2":        data["teams"][1],
        "score":        data["score"],
        "winner":       data["winner"],
        "format":       data["format"],
        "date":         data["date"],
        "status":       status,
        "playerStats":  clean_stats,
        "vlrId":        vlr_id,
    }

    existing_idx = next((i for i, m in enumerate(matches) if m["id"] == match_id), None)
    if existing_idx is not None:
        matches[existing_idx] = new_match
        print(f"  ↻ Updated existing match {match_id}")
    else:
        matches.append(new_match)
        print(f"  + Added new match {match_id}")

    # Save after every match so progress isn't lost if a later match fails
    vs.save_json(matches_file, matches)
    return True, unmatched_context


# ── Main ─────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tournament-id", help="Force a specific tournament ID instead of auto-detecting 'ongoing'")
    parser.add_argument("--include-upcoming", action="store_true",
                         help="List upcoming (not-yet-played) matches too (still skipped — nothing to scrape yet)")
    parser.add_argument("--matches-file",     default="data/matches.json")
    parser.add_argument("--tournaments-file", default="data/tournaments.json")
    parser.add_argument("--players-file",     default="data/players.json")
    parser.add_argument("--delay", type=float, default=2.0,
                         help="Seconds to wait between match requests (politeness delay)")
    parser.add_argument("--unattended", action="store_true",
                         help="Never block on input(); skip any match where total rounds "
                              "can't be auto-detected instead of prompting for it")
    args = parser.parse_args()

    tournaments  = vs.load_json(args.tournaments_file)
    players_data = vs.load_json(args.players_file)
    matches      = vs.load_json(args.matches_file)

    if args.tournament_id:
        tournament = next((t for t in tournaments if t["id"] == args.tournament_id), None)
        if not tournament:
            print(f"No tournament with id '{args.tournament_id}' found in {args.tournaments_file}.")
            sys.exit(1)
    else:
        ongoing = find_ongoing_tournaments(tournaments)
        if not ongoing:
            print("No tournament with status 'ongoing' found in tournaments.json.")
            sys.exit(0)
        tournament = pick_tournament(ongoing)

    tournament_id = tournament["id"]
    print(f"\n=== Ongoing tournament: {tournament['name']} (id={tournament_id}) ===")

    url = get_event_matches_url(tournament_id)
    html = vs.fetch_page(url)
    if not html:
        print("Could not fetch the tournament matches page.")
        sys.exit(1)

    all_matches = extract_match_ids(html)
    if not all_matches:
        print("No matches found on the tournament page. VLR may have changed its HTML — check selectors.")
        sys.exit(1)

    existing_vlr_ids = {m.get("vlrId") for m in matches if m.get("vlrId")}

    to_scrape = []
    for match_id, is_completed in all_matches:
        if match_id in existing_vlr_ids:
            continue
        if not is_completed:
            if args.include_upcoming:
                print(f"  (skipping {match_id} — not completed yet)")
            continue
        to_scrape.append(match_id)

    print(f"\nFound {len(all_matches)} total match(es) on VLR, {len(to_scrape)} new completed match(es) to scrape.")

    if not to_scrape:
        print("Nothing new to scrape. matches.json is already up to date.")
        return

    scraped = 0
    skipped = 0
    all_unmatched = []
    for i, match_id in enumerate(to_scrape, 1):
        print(f"\n[{i}/{len(to_scrape)}] Match {match_id}")
        ok, unmatched = scrape_match(match_id, tournament_id, players_data, matches,
                                      args.matches_file, unattended=args.unattended)
        if ok:
            scraped += 1
        else:
            skipped += 1
        all_unmatched.extend(unmatched)
        if i < len(to_scrape):
            time.sleep(args.delay)

    print(f"\n✓ Done. Scraped {scraped}/{len(to_scrape)} new match(es).")
    if skipped:
        print(f"  ⚠ {skipped} match(es) skipped (see warnings above).")
    print(f"  Total matches in {args.matches_file}: {len(matches)}")

    if all_unmatched:
        # Group by player name, since the same unmatched player can show
        # up across several matches in the same tournament.
        by_name = {}
        for entry in all_unmatched:
            by_name.setdefault(entry["name"], []).append(entry)

        print(f"\n⚠ {len(by_name)} unique player(s) had no match in {args.players_file}:")
        for name, entries in sorted(by_name.items()):
            teams = sorted({e["team"] for e in entries})
            print(f"  - {name}  ({'/'.join(teams)})  — {len(entries)} match(es)")
        print(f"  These were saved with their raw VLR name as playerId. "
              f"Add them to {args.players_file} and re-run to link them properly.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCancelled.")
        sys.exit(0)
