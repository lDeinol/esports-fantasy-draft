#!/usr/bin/env python3
"""
vlr_scrape.py — Scrape a VLR.gg match and save it to data/matches.json

Usage:
    python3 tools/vlr_scrape.py
    python3 tools/vlr_scrape.py --url https://www.vlr.gg/684619
    python3 tools/vlr_scrape.py --id 684619

Run from your project root (where data/ lives).

Requirements:
    pip install requests beautifulsoup4
"""

import json
import os
import sys
import re
import argparse
import time
from datetime import date

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Missing dependencies. Run: pip install requests beautifulsoup4")
    sys.exit(1)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.vlr.gg/",
}


# ── Helpers ────────────────────────────────────────────────
def load_json(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        content = f.read().strip()
    if not content:
        print(f"  ⚠ {path} exists but is empty — treating it as an empty list.")
        return []
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        print(f"  ⚠ {path} contains invalid JSON ({e}). Treating it as an empty list.")
        print(f"    Check that this is really the file you meant to point at.")
        return []


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def prompt(label, required=True, default=None):
    while True:
        suffix = f" [{default}]" if default is not None else ""
        val = input(f"{label}{suffix}: ").strip()
        if not val and default is not None:
            return default
        if not val and required:
            print("  This field is required.")
            continue
        return val


def safe_float(val, fallback=0.0):
    try:
        return round(float(val), 2)
    except (ValueError, TypeError):
        return fallback


def safe_int(val, fallback=0):
    try:
        return int(val)
    except (ValueError, TypeError):
        return fallback


def resolve_team_name(raw_name):
    """If team name contains a parenthetical e.g. 'AG.AL (All Gamers)',
    automatically use the full name in parentheses — no prompt."""
    m = re.match(r"^(.+?)\s*\((.+?)\)\s*$", raw_name.strip())
    if not m:
        return raw_name
    full_name = m.group(2).strip()
    print(f"  Team name '{raw_name}' -> using '{full_name}'")
    return full_name


def resolve_status(date_str, has_score):
    """Return 'upcoming' or 'completed' based on date vs today and whether a score exists."""
    if not date_str:
        return "completed" if has_score else "upcoming"
    try:
        match_date = date.fromisoformat(date_str)
        if match_date > date.today():
            return "upcoming"
    except ValueError:
        pass
    return "completed" if has_score else "upcoming"
    """Return 'upcoming', or 'completed' based on date vs today and whether a score exists."""
    if not date_str:
        return "completed" if has_score else "upcoming"
    try:
        match_date = date.fromisoformat(date_str)
        if match_date > date.today():
            return "upcoming"
    except ValueError:
        pass
    return "completed" if has_score else "upcoming"


# ── Fetch page ─────────────────────────────────────────────
def fetch_page(url):
    print(f"  Fetching {url} …")
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return r.text
    except requests.exceptions.HTTPError as e:
        print(f"  HTTP error: {e}")
        return None
    except requests.exceptions.ConnectionError:
        print("  Connection error — check your internet connection.")
        return None
    except requests.exceptions.Timeout:
        print("  Request timed out.")
        return None


# ── Auto-detect total rounds played ─────────────────────────
def auto_total_rounds(soup):
    """
    Sum the final round score of every played map to get the series
    total rounds (used for KPR). Each map is a '.vm-stats-game'
    container with its own data-game-id; the aggregate 'all' tab is
    skipped since it isn't an individual map.
    Returns 0 if it can't confidently determine this (caller should
    fall back to asking the user).
    """
    total = 0
    found_any_map = False

    for game in soup.select(".vm-stats-game"):
        gid = game.get("data-game-id", "")
        if gid == "all":
            continue

        score_els = game.select(".vm-stats-game-header .team .score")
        if len(score_els) < 2:
            continue

        map_scores = []
        for el in score_els[:2]:
            text = el.get_text(strip=True)
            if text.isdigit():
                map_scores.append(int(text))

        if len(map_scores) == 2:
            # Skip maps that were never played (both scores 0 with no
            # winner indicator) — e.g. a decider map when the series
            # already ended 2-0.
            if map_scores[0] == 0 and map_scores[1] == 0:
                continue
            total += map_scores[0] + map_scores[1]
            found_any_map = True

    return total if found_any_map else 0


# ── Parse match ────────────────────────────────────────────
def parse_match(html, match_id):
    soup = BeautifulSoup(html, "html.parser")

    # ── Teams ──────────────────────────────────────────────
    team_els = soup.select(".match-header-link-name .wf-title-med")
    if len(team_els) < 2:
        # Fallback selector used on some match pages
        team_els = soup.select(".wf-title-med")
    teams = [t.get_text(strip=True) for t in team_els[:2]]
    if len(teams) < 2:
        print("  ⚠ Could not find team names.")
        teams = ["Team 1", "Team 2"]

    # Resolve any "Short (Full Name)" format for each team
    teams = [resolve_team_name(t) for t in teams]

    # ── Score ──────────────────────────────────────────────
    score_el = soup.select(".match-header-vs-score .js-spoiler span")
    scores = [s.get_text(strip=True) for s in score_el if s.get_text(strip=True).isdigit()]
    score_str = f"{scores[0]}-{scores[1]}" if len(scores) >= 2 else None

    winner = None
    if score_str:
        s1, s2 = int(scores[0]), int(scores[1])
        winner = teams[0] if s1 > s2 else teams[1] if s2 > s1 else None

    # ── Format (BO1/BO3/BO5) ──────────────────────────────
    fmt = "BO3"
    if score_str:
        max_maps = max(int(scores[0]), int(scores[1])) if len(scores) >= 2 else 0
        if max_maps == 1:   fmt = "BO1"
        elif max_maps == 2: fmt = "BO3"
        elif max_maps >= 3: fmt = "BO5"

    # ── Date ──────────────────────────────────────────────
    date_el = soup.select_one(".match-header-date .moment-tz-convert")
    if not date_el:
        date_el = soup.select_one("div.moment-tz-convert")
    date_str = ""
    if date_el and date_el.get("data-utc-ts"):
        ts = date_el["data-utc-ts"]
        # Format is like "2024-06-01 18:00:00"
        date_str = ts[:10]
    else:
        # Try to find any date text
        date_el = soup.select_one(".match-header-date")
        if date_el:
            raw = date_el.get_text(" ", strip=True)
            m = re.search(r"(\d{4}-\d{2}-\d{2})", raw)
            if m:
                date_str = m.group(1)

    # ── Tournament ─────────────────────────────────────────
    event_el = soup.select_one(".match-header-event-series") or soup.select_one(".match-header-event")
    event_name = event_el.get_text(" ", strip=True) if event_el else ""

    # ── Player stats from the "all" (series total) tab ────
    # VLR shows per-map tabs + an "all" tab with series totals
    game_all = soup.select_one('.vm-stats-game[data-game-id="all"]')
    if not game_all:
        # Some pages only have per-map data — use first map
        game_all = soup.select_one(".vm-stats-game")

    player_stats = []
    rounds_total = 0

    if game_all and score_str:
        # Only parse stats if the match has a score.
        # Try to auto-derive total rounds from the per-map scores first.
        rounds_total = auto_total_rounds(soup)
        if rounds_total > 0:
            print(f"  Auto-detected total rounds: {rounds_total}")
        else:
            print("  ⚠ Could not auto-detect total rounds from the page.")
            rounds_total = int(input("Enter Total Rounds: "))

        rows = game_all.select("tbody tr")
        current_team_idx = 0
        team_row_counts = [0, 0]

        for row in rows:
            # Detect team separator rows (they have colspan or no player name)
            name_el = (
                row.select_one(".mod-player .text-of") or
                row.select_one(".mod-player a div") or
                row.select_one(".mod-player")
            )
            if not name_el:
                continue

            player_name = name_el.get_text(strip=True)
            if not player_name:
                continue

            # VLR stat columns (series totals tab):y
            # Rating | ACS | K | D | A | KD+/- | KAST | ADR | HS% | FK | FD | FK+/-
            stat_cells = row.select(".mod-stat")
            both_vals = []
            for cell in stat_cells:
                both = cell.select_one(".side.mod-both")
                if both:
                    both_vals.append(both.get_text(strip=True))
                else:
                    # Try getting any text from the cell
                    both_vals.append(cell.get_text(strip=True))

            # Map column indices — VLR "All" tab order:
            # 0=Rating, 1=ACS, 2=K, 3=D, 4=A, 5=KD+/-, 6=KAST, 7=ADR, 8=HS%, 9=FK, 10=FD
            rating = safe_float(both_vals[0]) if len(both_vals) > 0 else 0
            acs    = safe_float(both_vals[1]) if len(both_vals) > 1 else 0
            kills  = safe_int(both_vals[2])   if len(both_vals) > 2 else 0
            deaths = safe_int(both_vals[3])   if len(both_vals) > 3 else 0
            adr    = safe_float(both_vals[7]) if len(both_vals) > 7 else 0

            kd  = round(kills / deaths, 2) if deaths > 0 else float(kills)
            kpr = round(kills / rounds_total, 2) if rounds_total > 0 else 0

            # Assign team — first 5 players are team1, next 5 are team2
            team_idx = 0 if len([p for p in player_stats if p["team"] == teams[0]]) < 5 else 1
            team_name = teams[team_idx] if team_idx < len(teams) else teams[0]

            player_stats.append({
                "playerId": player_name,   # raw name — matched later
                "playerName": player_name,
                "team": team_name,
                "rating": rating,
                "kd": kd,
                "acs": acs,
                "adr": adr,
                "kpr": kpr,
            })

    return {
        "teams": teams,
        "score": score_str,
        "winner": winner,
        "format": fmt,
        "date": date_str,
        "eventName": event_name,
        "roundsTotal": rounds_total,
        "playerStats": player_stats,
    }


# ── Match player names to players.json IDs ─────────────────
def match_player_ids(player_stats, players_data):
    player_map = {}
    for p in players_data:
        player_map[p["name"].lower()] = p["id"]
        player_map[p["id"].lower()]   = p["id"]

    unmatched = []
    for stat in player_stats:
        raw = stat["playerName"].lower()
        matched_id = player_map.get(raw)
        if matched_id:
            stat["playerId"] = matched_id
        else:
            # Partial match
            partial = [pid for name, pid in player_map.items() if raw in name or name in raw]
            if partial:
                stat["playerId"] = partial[0]
            else:
                unmatched.append(stat["playerName"])
                stat["playerId"] = stat["playerName"]  # keep raw as fallback

    return unmatched


# ── Pick tournament from list ──────────────────────────────
def pick_tournament(tournaments):
    if not tournaments:
        print("  No tournaments found in tournaments.json.")
        return ""
    print("\nAvailable tournaments:")
    for i, t in enumerate(tournaments, 1):
        print(f"  {i}. {t['name']}  [{t['status']}]")
    while True:
        val = prompt("Select tournament number (or press Enter to skip)", required=False, default="")
        if val == "":
            return ""
        try:
            idx = int(val) - 1
            if 0 <= idx < len(tournaments):
                return tournaments[idx]["id"]
        except ValueError:
            pass
        print("  Enter a valid number.")


# ── Main ───────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url",           help="Full VLR.gg match URL")
    parser.add_argument("--id",            help="VLR.gg match ID number")
    parser.add_argument("--matches-file",     default="data/matches.json")
    parser.add_argument("--tournaments-file", default="data/tournaments.json")
    parser.add_argument("--players-file",     default="data/players.json")
    args = parser.parse_args()

    players_data    = load_json(args.players_file)
    tournaments     = load_json(args.tournaments_file)
    matches         = load_json(args.matches_file)
    existing_ids    = {m["id"] for m in matches}

    print("\n=== VLR.gg Match Scraper ===\n")

    # ── Get URL ────────────────────────────────────────────
    if args.url:
        url = args.url
    elif args.id:
        url = f"https://www.vlr.gg/{args.id}"
    else:
        raw = prompt("VLR.gg match URL or ID (e.g. 684619 or https://www.vlr.gg/684619)")
        raw = raw.strip()
        url = raw if raw.startswith("http") else f"https://www.vlr.gg/{raw}"

    # Extract numeric match ID from URL
    m = re.search(r"vlr\.gg/(\d+)", url)
    vlr_id = m.group(1) if m else re.sub(r"\D", "", url)
    if not vlr_id:
        print("Could not extract a match ID from the URL.")
        sys.exit(1)

    url = f"https://www.vlr.gg/{vlr_id}"

    # ── Fetch & parse ──────────────────────────────────────
    html = fetch_page(url)
    if not html:
        sys.exit(1)

    data = parse_match(html, vlr_id)

    print(f"\n  ✓ Parsed match: {data['teams'][0]} vs {data['teams'][1]}")
    print(f"    Score:   {data['score'] or 'N/A'}")
    print(f"    Winner:  {data['winner'] or 'N/A'}")
    print(f"    Format:  {data['format']}")
    print(f"    Date:    {data['date'] or 'unknown'}")
    print(f"    Event:   {data['eventName'] or 'unknown'}")
    print(f"    Rounds:  {data['roundsTotal']}")
    print(f"    Players: {len(data['playerStats'])}")

    # ── Player ID matching ─────────────────────────────────
    unmatched = match_player_ids(data["playerStats"], players_data)
    if unmatched:
        print(f"\n  ⚠ {len(unmatched)} player(s) not found in players.json:")
        for name in unmatched:
            print(f"    - {name}  (stored as-is; add with add_player.py to link properly)")
    else:
        print(f"\n  ✓ All {len(data['playerStats'])} players matched to players.json")

    # Show parsed player stats for review
    print("\n  Player stats preview:")
    for p in data["playerStats"]:
        print(f"    {p['playerName']:<14} [{p['team']:<14}]  Rating:{p['rating']}  K/D:{p['kd']}  ACS:{p['acs']}  ADR:{p['adr']}  KPR:{p['kpr']}")

    # ── Confirm before saving ──────────────────────────────
    ok = prompt("\nLooks good? Save to matches.json? (y/n)", default="y")
    if ok.lower() != "y":
        print("Cancelled.")
        sys.exit(0)

    # ── Tournament ─────────────────────────────────────────
    tournament_id = pick_tournament(tournaments)

    # ── Match ID ───────────────────────────────────────────
    default_match_id = vlr_id
    match_id = prompt(f"Match ID for matches.json", default=default_match_id)

    # ── Auto-determine status from date ───────────────────
    status = resolve_status(data["date"], bool(data["score"]))
    print(f"  → Status set to: {status}  (match date: {data['date'] or 'unknown'})")

    # ── Build clean stats (skip if upcoming) ──────────────
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

    # ── Update in place if ID exists, otherwise append ────
    existing_idx = next((i for i, m in enumerate(matches) if m["id"] == match_id), None)
    if existing_idx is not None:
        old = matches[existing_idx]
        matches[existing_idx] = new_match
        print(f"\n✓ Updated existing match '{data['teams'][0]} vs {data['teams'][1]}' ({match_id})")
        print(f"  Status: {old.get('status', '?')} → {status}")
    else:
        matches.append(new_match)
        print(f"\n✓ Saved new match '{data['teams'][0]} vs {data['teams'][1]}' ({match_id})")

    save_json(args.matches_file, matches)
    print(f"  Total matches in {args.matches_file}: {len(matches)}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCancelled.")
        sys.exit(0)
