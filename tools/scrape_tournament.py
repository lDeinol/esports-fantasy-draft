#!/usr/bin/env python3
"""
scrape_tournament.py — Find every ongoing tournament in tournaments.json,
pull the full match list for each from VLR.gg, and scrape any matches
that aren't already up to date in matches.json.

How it works:
    1. Reads tournaments.json, finds every tournament with status == "ongoing".
    2. For each one, fetches https://www.vlr.gg/event/matches/{tournament_id}/?series_id=all
    3. Scans every element with class "wf-card" for <a href="/12345/..."> links
       and pulls out the numeric match ID (first path segment).
    4. Decides what to (re-)scrape by comparing against our own matches.json,
       not VLR's list-page labels:
         - Not in matches.json at all       -> scrape it (even if it's still
           "Upcoming" on VLR — we still want its date saved).
         - Already in matches.json marked "upcoming" or "live" -> scrape it
           again, since that's exactly the case where new data (a score) may
           now be available.
         - Already in matches.json marked "completed"          -> skip it.
    5. For every match scraped, reuses vlr_scrape.py's own fetch_page() /
       parse_match() / match_player_ids() / resolve_status() logic and
       writes/updates it in matches.json — same schema as vlr_scrape.py
       produces, with tournamentId set to the tournament's numeric VLR id
       (matches the "id" field in tournaments.json). resolve_status() is
       what actually decides the saved status for each match:
       "completed" once a score is parsed, "live" once the match's date
       has arrived but no score exists yet, otherwise "upcoming" — so a
       match naturally flips upcoming -> live -> completed across runs as
       real data becomes available, and only ever gets marked "completed"
       once real score data has actually been parsed for it.

Each tournament's matches are scraped with a single, in-place progress
bar line rather than a running log — pass --verbose if you want the old
per-match detail printed instead.

Usage:
    python3 scrape_tournament.py                  # every ongoing tournament
    python3 scrape_tournament.py --tournament-id 2952   # just this one

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
import shutil
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


# ── Progress bar ─────────────────────────────────────────────
def print_progress(prefix, current, total, extra=""):
    """
    Render a single in-place progress bar line:
        Tournament Name              [###########-------]  8/12  TeamA vs TeamB (13-9)
    Overwrites the previous line via \\r; prints a trailing newline once
    current reaches total so the next tournament starts on a fresh line.
    """
    term_width = shutil.get_terminal_size(fallback=(100, 20)).columns
    bar_width = 24
    filled = int(bar_width * current / total) if total else bar_width
    bar = "#" * filled + "-" * (bar_width - filled)
    count_str = f"{current}/{total}"
    line = f"{prefix} [{bar}] {count_str}"
    if extra:
        line += f"  {extra}"
    # Pad to terminal width (minus a hair) so a shorter line fully
    # overwrites a longer one left over from the previous match.
    pad_width = max(term_width - 1, len(line))
    sys.stdout.write("\r" + line[:pad_width].ljust(pad_width))
    sys.stdout.flush()
    if current >= total:
        sys.stdout.write("\n")


# ── Scrape the event's match list page ──────────────────────
def get_event_matches_url(tournament_id):
    return f"https://www.vlr.gg/event/matches/{tournament_id}/?series_id=all"


def extract_match_ids(html):
    """
    Parse the VLR event matches page.
    Returns a list of match IDs, in page order, deduplicated.

    Status ("Upcoming" / "LIVE" / "Completed") isn't read off this list
    page — whether to (re-)scrape a given match is decided in
    scrape_tournament() by comparing against matches.json, and the saved
    status itself comes from resolve_status() against the real match
    page's date/score, which is far more reliable than the list page's
    label.
    """
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    match_ids = []

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
            match_ids.append(match_id)

    return match_ids


# ── Scrape a single match into matches.json ─────────────────
def scrape_match(vlr_id, tournament_id, players_data, matches, matches_file,
                  unattended=False, verbose=False):
    """
    Returns (ok, unmatched_context, label, warning):
        ok                 - True if the match was scraped/updated successfully
        unmatched_context  - list of {"name", "team", "match"} dicts for players
                              vlr_scrape.match_player_ids() couldn't match
        label              - short "TeamA vs TeamB (score)" string for progress
                              display, or None if the match couldn't be fetched
        warning            - one-line warning string to surface after the
                              progress bar finishes, or None
    """
    url = f"https://www.vlr.gg/{vlr_id}"
    html = vs.fetch_page(url)
    if not html:
        return False, [], None, f"Match {vlr_id}: could not fetch page, skipped."

    if unattended:
        original_input = builtins.input
        builtins.input = _disabled_input
        try:
            data = vs.parse_match(html, vlr_id)
        except RoundsPromptBlocked:
            return False, [], None, (
                f"Match {vlr_id}: could not auto-detect total rounds, skipped "
                f"(run again without --unattended to enter manually).")
        finally:
            builtins.input = original_input
    else:
        data = vs.parse_match(html, vlr_id)

    label = f"{data['teams'][0]} vs {data['teams'][1]} ({data['score'] or 'N/A'})"

    if verbose:
        print(f"\n  ✓ Parsed match: {data['teams'][0]} vs {data['teams'][1]}")
        print(f"    Score:  {data['score'] or 'N/A'}   Winner: {data['winner'] or 'N/A'}")
        print(f"    Date:   {data['date'] or 'unknown'}   Format: {data['format']}")

    unmatched_names = vs.match_player_ids(data["playerStats"], players_data)
    unmatched_context = []
    warning = None
    if unmatched_names:
        warning = f"Match {vlr_id} ({label}): unmatched player(s): {', '.join(unmatched_names)}"
        match_label = f"{data['teams'][0]} vs {data['teams'][1]}"
        for p in data["playerStats"]:
            if p["playerName"] in unmatched_names:
                unmatched_context.append({
                    "name":  p["playerName"],
                    "team":  p["team"],
                    "match": match_label,
                })
        if verbose:
            print(f"    ⚠ {len(unmatched_names)} unmatched player(s): {', '.join(unmatched_names)}")

    status = vs.resolve_status(data["date"], bool(data["score"]))

    # Only fill in real stats once the match is actually completed —
    # an "upcoming" or "live" match is saved with empty playerStats
    # (there's nothing to report yet) and gets re-scraped next run.
    clean_stats = []
    if status == "completed":
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
        "series":       data["series"],
        "team1":        data["teams"][0],
        "team2":        data["teams"][1],
        "score":        data["score"],
        "winner":       data["winner"],
        "format":       data["format"],
        "date":         data["date"],
        "status":       status,
        "playerStats":  clean_stats,
    }

    existing_idx = next((i for i, m in enumerate(matches) if m["id"] == match_id), None)
    if existing_idx is not None:
        matches[existing_idx] = new_match
        if verbose:
            print(f"  ↻ Updated existing match {match_id}")
    else:
        matches.append(new_match)
        if verbose:
            print(f"  + Added new match {match_id}")

    # Save after every match so progress isn't lost if a later match fails
    vs.save_json(matches_file, matches)
    return True, unmatched_context, label, warning


# ── Scrape one tournament (single progress-bar line) ─────────
def scrape_tournament(tournament, players_data, matches, args, index=1, total_tournaments=1):
    tournament_id = tournament["id"]
    name = tournament["name"]
    print(f"\n=== [{index}/{total_tournaments}] {name} (id={tournament_id}) ===")

    url = get_event_matches_url(tournament_id)
    html = vs.fetch_page(url)
    if not html:
        print("  Could not fetch the tournament matches page — skipping.")
        return 0, 0, []

    all_match_ids = extract_match_ids(html)
    if not all_match_ids:
        print("  No matches found on the tournament page. VLR may have changed its HTML — check selectors.")
        return 0, 0, []

    # Decide what to (re-)scrape from our own matches.json, not VLR's list-page
    # label: anything we don't have yet, or already have marked "upcoming" or
    # "live", gets (re-)scraped — that's exactly how a match's date gets saved
    # early and how it later picks up a score once one exists. Only matches we
    # already have as "completed" are skipped outright.
    existing_status_by_id = {m.get("id"): m.get("status") for m in matches if m.get("id")}

    to_scrape = [mid for mid in all_match_ids if existing_status_by_id.get(mid) != "completed"]
    already_done = len(all_match_ids) - len(to_scrape)

    if already_done:
        print(f"  ({already_done} match(es) already completed and up to date, skipped)")

    if not to_scrape:
        print(f"  Up to date — {len(all_match_ids)} match(es) on VLR, nothing to scrape.")
        return 0, 0, []

    scraped = 0
    skipped = 0
    warnings = []
    tournament_unmatched = []

    total = len(to_scrape)
    prefix = f"  {name[:28]:<28}"
    print_progress(prefix, 0, total)
    for i, match_id in enumerate(to_scrape, 1):
        ok, unmatched, label, warning = scrape_match(
            match_id, tournament_id, players_data, matches, args.matches_file,
            unattended=args.unattended, verbose=args.verbose)
        if ok:
            scraped += 1
        else:
            skipped += 1
        if warning:
            warnings.append(warning)
        tournament_unmatched.extend(unmatched)
        if not args.verbose:
            print_progress(prefix, i, total, extra=label or "")
        if i < total:
            time.sleep(args.delay)

    print(f"  ✓ {scraped}/{total} match(es) scraped/updated" + (f", {skipped} skipped" if skipped else ""))
    for w in warnings:
        print(f"  ⚠ {w}")

    return scraped, skipped, tournament_unmatched


# ── Main ─────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tournament-id", help="Only scrape this specific tournament ID instead of every 'ongoing' tournament")
    parser.add_argument("--matches-file",     default="data/matches.json")
    parser.add_argument("--tournaments-file", default="data/tournaments.json")
    parser.add_argument("--players-file",     default="data/players.json")
    parser.add_argument("--delay", type=float, default=2.0,
                         help="Seconds to wait between match requests (politeness delay)")
    parser.add_argument("--unattended", action="store_true",
                         help="Never block on input(); skip any match where total rounds "
                              "can't be auto-detected instead of prompting for it")
    parser.add_argument("--verbose", action="store_true",
                         help="Print full per-match detail (old behavior) instead of a "
                              "single-line progress bar per tournament")
    args = parser.parse_args()

    tournaments  = vs.load_json(args.tournaments_file)
    players_data = vs.load_json(args.players_file)
    matches      = vs.load_json(args.matches_file)

    if args.tournament_id:
        tournament = next((t for t in tournaments if t["id"] == args.tournament_id), None)
        if not tournament:
            print(f"No tournament with id '{args.tournament_id}' found in {args.tournaments_file}.")
            sys.exit(1)
        target_tournaments = [tournament]
    else:
        target_tournaments = find_ongoing_tournaments(tournaments)
        if not target_tournaments:
            print("No tournament with status 'ongoing' found in tournaments.json.")
            sys.exit(0)

    total_scraped = 0
    total_skipped = 0
    all_unmatched = []  # list of (tournament_name, unmatched_context) pairs

    for idx, tournament in enumerate(target_tournaments, 1):
        scraped, skipped, unmatched = scrape_tournament(
            tournament, players_data, matches, args,
            index=idx, total_tournaments=len(target_tournaments))
        total_scraped += scraped
        total_skipped += skipped
        if unmatched:
            all_unmatched.append((tournament["name"], unmatched))

    print(f"\n✓ Done. Scraped/updated {total_scraped} match(es) across "
          f"{len(target_tournaments)} tournament(s).")
    if total_skipped:
        print(f"  ⚠ {total_skipped} match(es) skipped (see warnings above).")
    print(f"  Total matches in {args.matches_file}: {len(matches)}")

    if all_unmatched:
        # Group by player name across all tournaments, since the same
        # unmatched player can show up in more than one.
        by_name = {}
        for _tournament_name, entries in all_unmatched:
            for entry in entries:
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
