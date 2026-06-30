# Data Entry Tools

Quick CLI scripts to add real data to `data/players.json`, `data/tournaments.json`,
and `data/matches.json` without hand-editing JSON.

## Requirements

Python 3.7+ (no extra packages needed — uses only the standard library).

## Usage

Run these from your **project root** (the folder containing `data/`), not from
inside the `tools/` folder:

```bash
# Add players
python3 tools/add_player.py

# Add tournaments
python3 tools/add_tournament.py

# Add matches (upcoming or already-completed)
python3 tools/add_match.py

# Update a match once it's finished (fill in score + stats)
python3 tools/update_match.py
```

Each script will prompt you field-by-field. Press Enter to accept defaults
shown in `[brackets]`. After each entry it asks "Add another? (y/n)" so you
can batch-add several at once in one run.

## Recommended workflow

1. **Add the tournament first** — `add_tournament.py`. Note the tournament ID
   it prints at the end; you'll need it (or just pick it from the list) when
   adding matches.
2. **Add players** — `add_player.py`. These are season-average stats used in
   the draft pool and stats page.
3. **Add matches as they're scheduled** — `add_match.py`, status = `upcoming`.
   You can skip score/stats at this point.
4. **After a match finishes** — `update_match.py`. Pick the match from the
   list, set status to `completed`, enter the score/winner, and type in each
   player's per-match stats. This is what feeds fantasy points.

## Notes

- All three scripts default to reading/writing `data/players.json`,
  `data/tournaments.json`, and `data/matches.json` relative to wherever you
  run them. Pass `--file path/to/file.json` (or `--matches-file`,
  `--tournaments-file`, `--players-file` for `add_match.py`/`update_match.py`)
  if your structure differs.
- `add_match.py` and `update_match.py` look up players by name or ID from
  `players.json`, so add players first.
- IDs must be unique. If you enter an existing ID, the script asks whether to
  overwrite that entry.
- Every script writes valid, pretty-printed JSON back to disk immediately
  after each entry — so even if you Ctrl+C partway through a batch, anything
  already entered is saved.
