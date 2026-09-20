// ============================================================
//  app.js — Shared logic for Esports Fantasy Draft
// ============================================================

import { initializeApp } from "https://www.gstatic.com/firebasejs/10.12.0/firebase-app.js";
import { getDatabase, ref, set, get, update, onValue, push } from "https://www.gstatic.com/firebasejs/10.12.0/firebase-database.js";
import { getAuth, signInAnonymously, onAuthStateChanged } from "https://www.gstatic.com/firebasejs/10.12.0/firebase-auth.js";

// ── Firebase Config ──────────────────────────────────────────
const firebaseConfig = {
  apiKey: "AIzaSyBwRS0zOZlHz8lbfQfEX3cPC9-60YcGvIs",
  authDomain: "esports-fantasy-draft.firebaseapp.com",
  databaseURL: "https://esports-fantasy-draft-default-rtdb.firebaseio.com",
  projectId: "esports-fantasy-draft",
  storageBucket: "esports-fantasy-draft.firebasestorage.app",
  messagingSenderId: "659806419720",
  appId: "1:659806419720:web:5c622d86ea1d93bf020abd"
};

const app  = initializeApp(firebaseConfig);
const db   = getDatabase(app);
const auth = getAuth(app);

export { db, auth, ref, set, get, update, onValue, push };

// ── Constants ────────────────────────────────────────────────
export const CONFIG = {
  ROSTER_SIZE:    5,
  AUCTION_BUDGET: 200,
  AUCTION_TIMER:  30,   // seconds per bid window
  MIN_BID:        1,
};

// ── Anonymous Auth ───────────────────────────────────────────
// Signs in anonymously if not already signed in.
// Returns a Promise that resolves to the Firebase user.
export function ensureAuth() {
  return new Promise((resolve, reject) => {
    const unsubscribe = onAuthStateChanged(auth, (user) => {
      unsubscribe();
      if (user) {
        resolve(user);
      } else {
        signInAnonymously(auth).then((cred) => resolve(cred.user)).catch(reject);
      }
    });
  });
}

// ── LocalStorage Helpers ─────────────────────────────────────
export const LS = {
  set(key, value) { localStorage.setItem(key, JSON.stringify(value)); },
  get(key)        { try { return JSON.parse(localStorage.getItem(key)); } catch { return null; } },
  clear(key)      { localStorage.removeItem(key); },

  saveSession({ uid, name, lobbyCode, isHost }) {
    this.set("session", { uid, name, lobbyCode, isHost });
  },
  getSession() {
    return this.get("session");
  },
  clearSession() {
    this.clear("session");
  },
};

// ── Lobby Code Generator ─────────────────────────────────────
export function generateCode(length = 6) {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"; // no ambiguous chars
  return Array.from({ length }, () => chars[Math.floor(Math.random() * chars.length)]).join("");
}

// ── Snake Draft Order ────────────────────────────────────────
// Given an ordered list of UIDs and a 0-based pick index,
// returns the UID whose turn it is.
export function getPickerUid(pickOrder, pickIndex) {
  const n     = pickOrder.length;
  const round = Math.floor(pickIndex / n);
  const pos   = pickIndex % n;
  // Even rounds go forward, odd rounds go backward (snake)
  return round % 2 === 0 ? pickOrder[pos] : pickOrder[n - 1 - pos];
}

// Returns total number of picks in the draft
export function totalPicks(numPlayers) {
  return numPlayers * CONFIG.ROSTER_SIZE;
}

// ── Placement Points (PP) ────────────────────────────────────
// For International-region tournaments only, winning a bracket round
// awards a flat bonus, regardless of how many matches a team played
// to get there. Keyed by the match's "series" label with the group
// letter / swiss record suffix stripped off — e.g.
// "Group Stage: Winner's (A)" and "Group Stage: Winner's (D)" both
// map to "Group Stage: Winner's". A round with no entry (or 0) awards
// no PP. This is the single source of truth — stats.html, dashboard.html,
// and standings.html all read from this rather than keeping their own copy.
export const PP_BY_SERIES = {
  "Group Stage: Opening":            0,
  "Group Stage: Winner's":           110,
  "Group Stage: Elimination":        0,
  "Group Stage: Decider":            0,
  "Swiss Stage: Round 1":            0,
  "Swiss Stage: Round 2":            100,
  "Swiss Stage: Round 3":            0,
  "Playoffs: Upper Quarterfinals":   0,
  "Playoffs: Upper Semifinals":      110,
  "Playoffs: Upper Final":           110,
  "Playoffs: Grand Final":           120,
  "Playoffs: Lower Round 1":         0,
  "Playoffs: Lower Round 2":         0,
  "Playoffs: Lower Round 3":         0,
  "Playoffs: Lower Final":           0,
  "Playoffs: Quarterfinals":         0,
  "Playoffs: Semifinals":            0,
  "Playoffs: Consolation Final":     0,
};

// Strips a trailing "(A)" group letter or "(1-0)" swiss record off a
// series label so it matches a PP_BY_SERIES key regardless of group
// or seed.
export function normalizeSeries(series) {
  return (series || "").replace(/\s*\([^)]*\)\s*$/, "").trim();
}

// ── Scoring Engine ───────────────────────────────────────────
// Valorant-specific scoring weights (CL% excluded — calculated end of tournament only)
export const SCORING = {
  weights: {
    rating: 40,
    kd:     25,
    acs:    0.15,
    adr:    0.10,
    kpr:    10,
  },
  calculate(stats = {}) {
    return Object.entries(this.weights).reduce((total, [key, weight]) => {
      return total + (stats[key] ?? 0) * weight;
    }, 0);
  },
  breakdown(stats = {}) {
    return Object.entries(this.weights).map(([key, weight]) => ({
      stat:   key.toUpperCase(),
      value:  stats[key] ?? 0,
      points: +((stats[key] ?? 0) * weight).toFixed(1),
    }));
  },
  // Same as totalFromMatches, but only counts matches whose date falls
  // within [from, to) — used to score a single ownership stint of a
  // traded player rather than the whole tournament, so points never
  // move retroactively when a player changes hands. from/to are epoch
  // ms; to defaults to Infinity ("still owned as of now").
  pointsInWindow(playerId, matches, tournamentId, from = 0, to = Infinity) {
    const filtered = matches.filter(m => {
      if (m.status !== "completed") return false;
      if (tournamentId && m.tournamentId !== tournamentId) return false;
      const ts = new Date(m.date + "T00:00:00").getTime();
      return ts >= from && ts < to;
    });
    return +filtered.reduce((total, m) => {
      const stats = m.playerStats?.find(s => s.playerId === playerId);
      return total + (stats ? this.calculate(stats) : 0);
    }, 0).toFixed(1);
  },
  // Calculate total points for a playerId from matches, filtered to a tournament
  // matches: full matches array, tournamentId: string or null (null = all matches)
  totalFromMatches(playerId, matches, tournamentId = null) {
    const filtered = matches.filter(m =>
      m.status === "completed" &&
      (!tournamentId || m.tournamentId === tournamentId)
    );
    return +filtered.reduce((total, m) => {
      const stats = m.playerStats?.find(s => s.playerId === playerId);
      return total + (stats ? this.calculate(stats) : 0);
    }, 0).toFixed(1);
  },
  // Per-match breakdown for a player filtered to a tournament
  matchHistory(playerId, matches, tournamentId = null) {
    return matches
      .filter(m =>
        m.status === "completed" &&
        (!tournamentId || m.tournamentId === tournamentId) &&
        m.playerStats?.some(s => s.playerId === playerId)
      )
      .map(m => {
        const stats = m.playerStats.find(s => s.playerId === playerId);
        return { match: m, stats, pts: +this.calculate(stats).toFixed(1) };
      });
  },
  // Same shape as matchHistory, but scoped to the given ownership stints
  // (only matches whose date falls within one of them). Use this — not
  // matchHistory — anywhere a manager's per-player match count, averaged
  // stats, or points need to agree with each other; matchHistory alone
  // is whole-tournament and will disagree with stint-scoped points once
  // a player's been traded.
  stintMatchHistory(playerId, matches, tournamentId, stints) {
    return this.matchHistory(playerId, matches, tournamentId).filter(h => {
      const ts = new Date(h.match.date + "T00:00:00").getTime();
      return stints.some(s => ts >= (s.from || 0) && ts < (s.to ?? Infinity));
    });
  },
  // Placement Points earned by a player within a single tournament.
  // Only awards PP when that tournament's region is "International" —
  // pass the full tournaments array so the region can be looked up.
  // Returns 0 for tournamentId === null (an "all tournaments" view has
  // no single region to check against).
  // from/to (epoch ms, to defaults to Infinity) optionally scope this to
  // a single ownership stint, same as pointsInWindow above — omit them
  // to get the old whole-tournament behavior.
  placementPoints(playerId, matches, tournamentId, tournaments, from = 0, to = Infinity) {
    if (!tournamentId) return 0;
    const tournament = tournaments?.find(t => t.id === tournamentId);
    if (tournament?.region !== "International") return 0;

    const wins = matches.filter(m => {
      if (m.status !== "completed" || m.tournamentId !== tournamentId || !m.winner) return false;
      if (!m.playerStats?.some(s => s.playerId === playerId && s.team === m.winner)) return false;
      const ts = new Date(m.date + "T00:00:00").getTime();
      return ts >= from && ts < to;
    });

    return +wins.reduce((total, m) => total + (PP_BY_SERIES[normalizeSeries(m.series)] || 0), 0).toFixed(1);
  },
  // Points + PP earned during a single ownership stint (see getOwnership
  // below) — from/to come straight off the stint record. `to: null`
  // means "still owned", scored through to right now.
  stintTotal(playerId, matches, tournamentId, tournaments, stint) {
    const from = stint.from || 0;
    const to   = stint.to ?? Infinity;
    const base = this.pointsInWindow(playerId, matches, tournamentId, from, to);
    const pp   = this.placementPoints(playerId, matches, tournamentId, tournaments, from, to);
    return { base, pp, total: +(base + pp).toFixed(1) };
  },
};

// ── Player Name Colors ───────────────────────────────────────
// Preset palette participants can choose from in the lobby to color
// their name wherever it appears (player list, draft board, etc).
export const PLAYER_COLORS = [
  "#ff4655", "#ff8a5c", "#f59e0b", "#facc15",
  "#d4d40a", "#4ade80", "#10b981", "#2dd4bf",
  "#34d399", "#00e5ff", "#38bdf8", "#60a5fa",
  "#818cf8", "#a78bfa", "#c084fc", "#e879f9",
  "#f472b6", "#ec4899", "#fb7185", "#f87171",
];

// Sets the calling player's chosen name color for a given lobby.
export async function setPlayerColor({ code, uid, color }) {
  await set(ref(db, `lobbies/${code}/players/${uid}/color`), color);
}

// ── Firebase Lobby Helpers ───────────────────────────────────

// Create a new lobby in Firebase
// maxPlayers caps how many players can join — normally set to the
// selected tournament's team count (one player drafts per team).
export async function createLobby({ code, hostUid, hostName, format, tournamentId, maxPlayers }) {
  const lobbyRef = ref(db, `lobbies/${code}`);
  await set(lobbyRef, {
    code,
    format,
    tournamentId:     tournamentId || null,
    maxPlayers:       maxPlayers || null,
    pickTimer:        null,
    status:           "waiting",
    hostId:           hostUid,
    createdAt:        Date.now(),
    currentPickIndex: 0,
    pickOrder:        [],
    players: {
      [hostUid]: { name: hostName, isHost: true, status: "active", joinedAt: Date.now() }
    },
    picks:             {},
    draftedPlayerIds:  [],
    auctionState:      null,
  });
}

// Add a player to an existing lobby.
// Re-checks the lobby's maxPlayers/current player count right before
// writing, so two people can't both squeeze into the last open slot.
export async function joinLobby({ code, uid, name }) {
  const lobbyRef = ref(db, `lobbies/${code}`);
  const snap = await get(lobbyRef);
  const lobby = snap.val();
  if (!lobby) throw new Error("Lobby not found.");

  const players = lobby.players || {};
  if (!players[uid] && lobby.maxPlayers) {
    // Only players still active in the lobby count against the cap —
    // someone who left frees their slot back up.
    const activeCount = Object.values(players).filter(p => p.status !== "left").length;
    if (activeCount >= lobby.maxPlayers) {
      throw new Error(`Lobby is full (${lobby.maxPlayers} / ${lobby.maxPlayers}).`);
    }
  }

  const playerRef = ref(db, `lobbies/${code}/players/${uid}`);
  await set(playerRef, { name, isHost: false, status: "active", joinedAt: Date.now() });
}

// Marks a player as having left the lobby WITHOUT deleting their data —
// their name, color, and (most importantly) their draft picks stay in
// place, so Standings/Dashboard keep showing them instead of the row
// just vanishing. This also means findPlayerByName can still find them
// later, which is what makes "leave by accident, rejoin with the same
// name" work at all.
//
// Pre-draft exception: if the HOST leaves before the draft has started,
// there's no data to preserve yet, so we still close the lobby for
// everyone (matches the old behavior). A host leaving DURING or AFTER
// a draft instead hands host duties to another still-active player so
// the lobby and everyone's picks stay intact.
export async function leavePlayer({ code, uid }) {
  const lobbyRef = ref(db, `lobbies/${code}`);
  const snap = await get(lobbyRef);
  const lobby = snap.val();
  if (!lobby) return;

  const players = lobby.players || {};
  const wasHost = lobby.hostId === uid;

  if (wasHost && lobby.status === "waiting") {
    await set(lobbyRef, null);
    return;
  }

  const updates = {};
  updates[`lobbies/${code}/players/${uid}/status`] = "left";
  updates[`lobbies/${code}/players/${uid}/leftAt`] = Date.now();

  if (wasHost) {
    const nextHost = Object.entries(players).find(
      ([otherUid, p]) => otherUid !== uid && p.status !== "left"
    );
    if (nextHost) {
      updates[`lobbies/${code}/hostId`] = nextHost[0];
      updates[`lobbies/${code}/players/${nextHost[0]}/isHost`] = true;
    }
    updates[`lobbies/${code}/players/${uid}/isHost`] = false;
  }

  await update(ref(db), updates);
}

// Marks a player active again — used whenever someone who previously
// left rejoins (whether their local session survived or not).
export async function rejoinPlayer({ code, uid }) {
  await update(ref(db, `lobbies/${code}/players/${uid}`), {
    status: "active",
    leftAt: null,
  });
}

// Check if a lobby exists and is still in "waiting" status
export async function lobbyExists(code) {
  const snap = await get(ref(db, `lobbies/${code}`));
  return snap.exists() ? snap.val() : null;
}

// Subscribe to live lobby updates (returns unsubscribe fn)
export function subscribeLobby(code, callback) {
  const lobbyRef = ref(db, `lobbies/${code}`);
  const unsub = onValue(lobbyRef, (snap) => callback(snap.val()));
  return unsub;
}

// ── Trades ───────────────────────────────────────────────────
// Trades let managers swap players post-draft without moving points
// retroactively: each pick tracks its own ownership history, and
// scoring (via SCORING.pointsInWindow/stintTotal above) only credits a
// manager for matches played while they actually held the player.

export const TRADE_REJECTION_LIMIT = 3;

// A pick's ownership history. Picks made before trades existed won't
// have this field yet — synthesize a single still-open stint owned by
// `byUid` since the pick was made, so old lobbies keep working.
export function getOwnership(pick) {
  if (Array.isArray(pick.ownership) && pick.ownership.length) return pick.ownership;
  return [{ uid: pick.byUid, from: pick.pickedAt || 0, to: null }];
}

// The uid currently holding this pick's player, or null if it's been
// traded away to the free-agent pool and nobody currently owns it.
export function currentOwnerUid(pick) {
  const ownership = getOwnership(pick);
  const last = ownership[ownership.length - 1];
  // Firebase Realtime Database treats a null value as "delete this key" —
  // so a still-open stint written as `to: null` comes back with no `to`
  // field at all (undefined), not null. Use == to catch both.
  return last.to == null ? last.uid : null;
}

// Builds one manager's roster + score from `picks`, honoring every pick's
// ownership stint history so trades never move points retroactively.
// Returns:
//   currentRoster — picks this uid owns right now, each with the points/PP
//                   earned across every stint *this uid* held them for
//                   (handles the rare trade-away-then-back-again case)
//   pastPlayers   — picks this uid owned at some point but no longer does;
//                   still contributes to totalScore, just not shown as a
//                   live roster slot
//   totalScore, totalPP — summed across current + past
export function computeRoster({ uid, picks, matchData, tournamentId, tournamentData }) {
  const currentRoster = [];
  const pastPlayers   = [];
  let totalScore = 0;
  let totalPP    = 0;

  Object.entries(picks || {}).forEach(([pickId, pick]) => {
    const ownership = getOwnership(pick);
    const myStints  = ownership.filter(s => s.uid === uid);
    if (myStints.length === 0) return;

    let pts = 0, pp = 0;
    myStints.forEach(stint => {
      const stintScore = SCORING.stintTotal(pick.playerId, matchData, tournamentId, tournamentData, stint);
      pts += stintScore.base;
      pp  += stintScore.pp;
    });
    pts = +pts.toFixed(1);
    pp  = +pp.toFixed(1);
    totalScore += pts + pp;
    totalPP    += pp;

    const entry = { pickId, pick, pts, pp, total: +(pts + pp).toFixed(1) };
    (currentOwnerUid(pick) === uid ? currentRoster : pastPlayers).push(entry);
  });

  return { currentRoster, pastPlayers, totalScore: +totalScore.toFixed(1), totalPP: +totalPP.toFixed(1) };
}

// Host starts a trade phase (mid-tournament break). `order` is the
// turn queue, already sorted worst-score-first by the caller — app.js
// doesn't fetch match/tournament data itself, so it can't compute
// standings on its own. roundCount is capped 1-3 by the UI.
export async function startTradePhase({ code, roundCount, order }) {
  await set(ref(db, `lobbies/${code}/tradePhase`), {
    active: true,
    roundCount,
    currentRound: 1,
    order,
    currentIndex: 0,
    rejectionCount: 0,
    startedAt: Date.now(),
    endedAt: null,
  });
}

// Host ends the trade phase early. Also clears any still-pending
// proposal — otherwise it could dangle forever with no turn queue
// left to resolve it against.
export async function endTradePhase({ code }) {
  const snap  = await get(ref(db, `lobbies/${code}`));
  const lobby = snap.val();

  const updates = {};
  updates[`lobbies/${code}/tradePhase/active`]  = false;
  updates[`lobbies/${code}/tradePhase/endedAt`] = Date.now();

  Object.entries(lobby?.trades || {}).forEach(([tradeId, trade]) => {
    if (trade.status === "pending") {
      updates[`lobbies/${code}/trades/${tradeId}/status`]      = "cancelled";
      updates[`lobbies/${code}/trades/${tradeId}/respondedAt`] = Date.now();
    }
  });

  await update(ref(db), updates);
}

// Shared turn-advance logic used by a completed trade, a voluntary
// pass, a host force-pass, or hitting the rejection limit. Cancels any
// proposal the outgoing manager still has pending (it shouldn't sit
// there respondable once their turn has moved on), resets the
// rejection counter, and rolls into the next round or closes the
// phase once the last manager in the last round is done.
async function advanceTurn(code) {
  const snap  = await get(ref(db, `lobbies/${code}`));
  const lobby = snap.val();
  const phase = lobby?.tradePhase;
  if (!phase || !phase.active) return;

  const outgoingUid = phase.order[phase.currentIndex];
  const updates = {};

  Object.entries(lobby.trades || {}).forEach(([tradeId, trade]) => {
    if (trade.status === "pending" && trade.proposedBy === outgoingUid) {
      updates[`lobbies/${code}/trades/${tradeId}/status`]      = "cancelled";
      updates[`lobbies/${code}/trades/${tradeId}/respondedAt`] = Date.now();
    }
  });

  let nextIndex = phase.currentIndex + 1;
  let nextRound = phase.currentRound;
  if (nextIndex >= phase.order.length) {
    nextIndex = 0;
    nextRound += 1;
  }

  if (nextRound > phase.roundCount) {
    updates[`lobbies/${code}/tradePhase/active`]  = false;
    updates[`lobbies/${code}/tradePhase/endedAt`] = Date.now();
  } else {
    updates[`lobbies/${code}/tradePhase/currentIndex`]   = nextIndex;
    updates[`lobbies/${code}/tradePhase/currentRound`]   = nextRound;
    updates[`lobbies/${code}/tradePhase/rejectionCount`] = 0;
  }

  await update(ref(db), updates);
}

// Manager voluntarily ends their own turn with no trade.
export async function passTurn({ code }) {
  await advanceTurn(code);
}

// Host ends the current manager's turn on the spot (used instead of a
// timer).
export async function hostForcePass({ code }) {
  await advanceTurn(code);
}

// Performs the actual player swap for an accepted trade: closes out
// the old ownership stint(s) and opens new one(s). Every past stint is
// left untouched, which is what makes past points stick with whoever
// earned them. Manager-to-manager trades swap two existing picks;
// undrafted-player pickups release the offered pick to the free-agent
// pool (closed with no new stint) and create a brand-new pick entry
// for the newly-acquired player.
async function executeTrade({ code, tradeId }) {
  const snap  = await get(ref(db, `lobbies/${code}`));
  const lobby = snap.val();
  const trade = lobby?.trades?.[tradeId];
  const offerPick = lobby?.picks?.[trade?.offerPickId];
  if (!trade || !offerPick) return;

  const now = Date.now();
  const updates = {};
  updates[`lobbies/${code}/trades/${tradeId}/status`]      = "accepted";
  updates[`lobbies/${code}/trades/${tradeId}/respondedAt`] = now;

  const offerOwnership = getOwnership(offerPick).slice();
  offerOwnership[offerOwnership.length - 1] = { ...offerOwnership[offerOwnership.length - 1], to: now };

  if (trade.requestPickId) {
    const requestPick = lobby.picks?.[trade.requestPickId];
    if (!requestPick) return;
    const requestOwnership = getOwnership(requestPick).slice();
    requestOwnership[requestOwnership.length - 1] = { ...requestOwnership[requestOwnership.length - 1], to: now };

    updates[`lobbies/${code}/picks/${trade.offerPickId}/ownership`] = [...offerOwnership, { uid: trade.proposedTo, from: now, to: null }];
    updates[`lobbies/${code}/picks/${trade.offerPickId}/byUid`]     = trade.proposedTo;

    updates[`lobbies/${code}/picks/${trade.requestPickId}/ownership`] = [...requestOwnership, { uid: trade.proposedBy, from: now, to: null }];
    updates[`lobbies/${code}/picks/${trade.requestPickId}/byUid`]     = trade.proposedBy;
  } else {
    updates[`lobbies/${code}/picks/${trade.offerPickId}/ownership`] = offerOwnership; // closed, no new stint = free agent
    updates[`lobbies/${code}/picks/${trade.offerPickId}/byUid`]     = null;

    const newPickRef = push(ref(db, `lobbies/${code}/picks`));
    updates[`lobbies/${code}/picks/${newPickRef.key}`] = {
      playerId:    trade.requestPlayerId,
      playerName:  trade.requestPlayerName,
      playerTeam:  trade.requestPlayerTeam || null,
      playerRole:  trade.requestPlayerRole || null,
      round: null, pick: null, label: "Trade",
      acquiredVia: "trade",
      byUid: trade.proposedBy,
      ownership: [{ uid: trade.proposedBy, from: now, to: null }],
    };

    const draftedIds = new Set(lobby.draftedPlayerIds || []);
    draftedIds.add(trade.requestPlayerId);
    updates[`lobbies/${code}/draftedPlayerIds`] = Array.from(draftedIds);
  }

  await update(ref(db), updates);
}

// Propose a trade. Pass requestPickId for a manager-to-manager trade
// (needs their acceptance); pass requestPlayerId/Name/Team/Role instead
// for an undrafted-player pickup, which has no counterparty and
// executes immediately, ending the turn on its own.
export async function proposeTrade({ code, round, proposedBy, proposedTo, offerPickId, requestPickId, requestPlayerId, requestPlayerName, requestPlayerTeam, requestPlayerRole }) {
  const tradeRef = push(ref(db, `lobbies/${code}/trades`));
  await set(tradeRef, {
    status: proposedTo ? "pending" : "accepted",
    round,
    proposedBy,
    proposedTo: proposedTo || null,
    offerPickId,
    requestPickId:     requestPickId     || null,
    requestPlayerId:   requestPlayerId   || null,
    requestPlayerName: requestPlayerName || null,
    requestPlayerTeam: requestPlayerTeam || null,
    requestPlayerRole: requestPlayerRole || null,
    createdAt: Date.now(),
    respondedAt: proposedTo ? null : Date.now(),
  });

  if (!proposedTo) {
    await executeTrade({ code, tradeId: tradeRef.key });
    await advanceTurn(code);
  }
  return tradeRef.key;
}

// The proposer cancels their own still-pending proposal, freeing them
// up to make a different one without burning a rejection.
export async function cancelTrade({ code, tradeId }) {
  await update(ref(db, `lobbies/${code}/trades/${tradeId}`), {
    status: "cancelled",
    respondedAt: Date.now(),
  });
}

// The receiving manager accepts or rejects a pending proposal.
export async function respondToTrade({ code, tradeId, accept }) {
  if (accept) {
    await executeTrade({ code, tradeId });
    await advanceTurn(code);
    return;
  }

  const snap  = await get(ref(db, `lobbies/${code}`));
  const lobby = snap.val();
  const phase = lobby?.tradePhase;

  const updates = {};
  updates[`lobbies/${code}/trades/${tradeId}/status`]      = "rejected";
  updates[`lobbies/${code}/trades/${tradeId}/respondedAt`] = Date.now();

  const nextRejectionCount = (phase?.rejectionCount || 0) + 1;
  if (nextRejectionCount >= TRADE_REJECTION_LIMIT) {
    await update(ref(db), updates);
    await advanceTurn(code); // resets rejectionCount as part of advancing
  } else {
    updates[`lobbies/${code}/tradePhase/rejectionCount`] = nextRejectionCount;
    await update(ref(db), updates);
  }
}

// ── Theme (Light / Dark) ─────────────────────────────────────
const THEME_KEY = "theme";

// Returns the currently active theme ("light" or "dark"), reading
// from localStorage. Defaults to "dark" (the site's original look).
export function getTheme() {
  try { return localStorage.getItem(THEME_KEY) === "light" ? "light" : "dark"; }
  catch { return "dark"; }
}

// Applies + persists a theme. "dark" removes the attribute entirely
// so it falls back to the default :root tokens in style.css.
export function setTheme(theme) {
  const isLight = theme === "light";
  if (isLight) document.documentElement.setAttribute("data-theme", "light");
  else document.documentElement.removeAttribute("data-theme");
  try { localStorage.setItem(THEME_KEY, isLight ? "light" : "dark"); } catch {}
}

// Wires up the header's theme-toggle checkbox: syncs its initial
// checked state to the active theme, and flips + persists on change.
// Call this once per page after the toggle markup exists in the DOM.
export function initThemeToggle(inputId = "theme-toggle-input") {
  const input = document.getElementById(inputId);
  if (!input) return;
  input.checked = getTheme() === "light";
  input.addEventListener("change", () => {
    setTheme(input.checked ? "light" : "dark");
  });
}

// ── Utility ──────────────────────────────────────────────────
export function formatCurrency(n) {
  return `$${Math.round(n)}`;
}

export function el(id) {
  return document.getElementById(id);
}

// Given a hex color (e.g. "#00e5ff"), returns "#000000" or "#ffffff" —
// whichever gives better contrast against it. Used for badges whose
// background is a data-driven color (team colors, etc.) that isn't
// tied to the light/dark theme, so the text needs to be picked per
// color rather than via the --text token.
export function contrastTextColor(hex) {
  if (!hex) return "#ffffff";
  const clean = hex.replace("#", "");
  const full  = clean.length === 3 ? clean.split("").map(c => c + c).join("") : clean;
  const r = parseInt(full.substring(0, 2), 16);
  const g = parseInt(full.substring(2, 4), 16);
  const b = parseInt(full.substring(4, 6), 16);
  if ([r, g, b].some(Number.isNaN)) return "#ffffff";
  // Relative luminance (WCAG-style approximation)
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return luminance > 0.6 ? "#000000" : "#ffffff";
}
