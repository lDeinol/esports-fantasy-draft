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
      [hostUid]: { name: hostName, isHost: true, joinedAt: Date.now() }
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
    const currentCount = Object.keys(players).length;
    if (currentCount >= lobby.maxPlayers) {
      throw new Error(`Lobby is full (${lobby.maxPlayers} / ${lobby.maxPlayers}).`);
    }
  }

  const playerRef = ref(db, `lobbies/${code}/players/${uid}`);
  await set(playerRef, { name, isHost: false, joinedAt: Date.now() });
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
<<<<<<< Updated upstream
=======

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

// ============================================================
//  Trading Phase
// ============================================================
//
// Data model added to lobbies/{code}:
//   tradingEnabled    bool   — host toggle
//   tradeRounds       number — how many full passes through tradeOrder
//   currentRound      number — 1-based
//   tradeOrder        [uid]  — snapshotted from standings (lowest score
//                              first) the moment the host starts trading;
//                              reused for every round
//   currentTurnIndex  number — index into tradeOrder
//   currentTurnUid    uid
//   attemptsThisTurn  number — rejected proposals in the current turn;
//                              hits 3 and the turn auto-passes
//   roster            { playerId: ownerUid }       — current owner of
//                      every drafted-or-traded player; missing entry
//                      means "in the undrafted pool"
//   ownershipLog      { playerId: { p0: {uid,from,to}, p1: ... } } —
//                      full history of who owned a player and when, so
//                      match points can be attributed to whoever owned
//                      the player at the time that match happened
//   trades            { tradeId: {...} }           — full trade log,
//                      visible to everyone

// Builds the trade turn order: every active manager, lowest total score
// first. Snapshotted once when trading starts and reused every round.
export function computeTradeOrder(lobbyData, matchData, tournamentData) {
  const { players, picks = {}, tournamentId } = lobbyData;
  const picksArr = Object.values(picks);
  const scored = Object.entries(players || {})
    .filter(([, p]) => p.status !== "left")
    .map(([uid]) => {
      const myPicks = picksArr.filter(pk => pk.byUid === uid);
      const total = myPicks.reduce((s, pk) => {
        const base = SCORING.totalFromMatches(pk.playerId, matchData, tournamentId);
        const pp   = SCORING.placementPoints(pk.playerId, matchData, tournamentId, tournamentData);
        return s + base + pp;
      }, 0);
      return { uid, total };
    });
  scored.sort((a, b) => a.total - b.total);
  return scored.map(s => s.uid);
}

// Fallback roster map for lobbies where trading has never been started —
// derives "who owns what" straight from the original draft picks.
export function buildRosterMap(lobbyData) {
  if (lobbyData.roster) return lobbyData.roster;
  const map = {};
  Object.values(lobbyData.picks || {}).forEach(pk => { map[pk.playerId] = pk.byUid; });
  return map;
}

// Ownership periods for a single player: [{ uid, from, to }], sorted
// oldest-first, `to: null` meaning "still owned". Falls back to a single
// all-time period under the original drafter if trading was never used.
export function getOwnershipPeriods(lobbyData, playerId) {
  const log = lobbyData.ownershipLog?.[playerId];
  if (log) return Object.values(log).sort((a, b) => a.from - b.from);
  const pick = Object.values(lobbyData.picks || {}).find(pk => pk.playerId === playerId);
  if (!pick) return [];
  return [{ uid: pick.byUid, from: 0, to: null }];
}

// Which uid owned a player at the moment a given match (by its YYYY-MM-DD
// date) kicked off. A trade that lands on the same day as a match: if the
// trade timestamp is before the match's start-of-day moment, the new
// owner gets it; a trade later that same day means the old owner keeps it
// (this falls out of `from` being inclusive / `to` being exclusive below).
export function ownerAtMatch(periods, matchDate) {
  const t = new Date(matchDate + "T00:00:00").getTime();
  const period = periods.find(p => p.from <= t && (p.to === null || t < p.to));
  return period ? period.uid : null;
}

// Players with no current owner in the roster map — draftable via trade.
export function getUndraftedPool(allPlayers, rosterMap) {
  return allPlayers.filter(p => !rosterMap[p.id]);
}

// Ownership-aware scoring — same shape as SCORING.totalFromMatches /
// matchHistory, but only counts a match toward `uid` if `uid` owned the
// player at the time. Safe to use even for lobbies with zero trades,
// since getOwnershipPeriods() falls back to "the drafter owns it always".
SCORING.totalFromMatchesOwned = function (playerId, matches, tournamentId, periods, uid) {
  const filtered = matches.filter(m =>
    m.status === "completed" &&
    (!tournamentId || m.tournamentId === tournamentId) &&
    ownerAtMatch(periods, m.date) === uid
  );
  return +filtered.reduce((total, m) => {
    const stats = m.playerStats?.find(s => s.playerId === playerId);
    return total + (stats ? this.calculate(stats) : 0);
  }, 0).toFixed(1);
};

SCORING.matchHistoryOwned = function (playerId, matches, tournamentId, periods, uid) {
  return matches
    .filter(m =>
      m.status === "completed" &&
      (!tournamentId || m.tournamentId === tournamentId) &&
      m.playerStats?.some(s => s.playerId === playerId) &&
      ownerAtMatch(periods, m.date) === uid
    )
    .map(m => {
      const stats = m.playerStats.find(s => s.playerId === playerId);
      return { match: m, stats, pts: +this.calculate(stats).toFixed(1) };
    });
};

// Ownership-aware Placement Points — same as SCORING.placementPoints but
// only credits a round win to `uid` if they owned the player at the time
// that win was recorded.
SCORING.placementPointsOwned = function (playerId, matches, tournamentId, tournaments, periods, uid) {
  if (!tournamentId) return 0;
  const tournament = tournaments?.find(t => t.id === tournamentId);
  if (tournament?.region !== "International") return 0;

  const wins = matches.filter(m =>
    m.status === "completed" &&
    m.tournamentId === tournamentId &&
    m.winner &&
    m.playerStats?.some(s => s.playerId === playerId && s.team === m.winner) &&
    ownerAtMatch(periods, m.date) === uid
  );

  return +wins.reduce((total, m) => total + (PP_BY_SERIES[normalizeSeries(m.series)] || 0), 0).toFixed(1);
};

// Points a manager earned from players they've since traded away — one
// entry per closed ownership period, scored only for matches that fell
// inside that window. These points are already folded into totalScore;
// this is a transparency breakdown of where some of it came from, for the
// dashboard's "Traded Away" section.
export function tradedAwayBreakdown(lobbyData, uid, matchData, tournamentId) {
  const log = lobbyData.ownershipLog || {};
  const results = [];
  Object.entries(log).forEach(([playerId, periodsObj]) => {
    const periods = Object.values(periodsObj).sort((a, b) => a.from - b.from);
    periods.forEach(period => {
      if (period.uid !== uid || period.to === null) return; // still owned = not "away"
      const pts = SCORING.totalFromMatchesOwned(playerId, matchData, tournamentId, [period], uid);
      if (pts > 0) results.push({ playerId, pts, from: period.from, to: period.to });
    });
  });
  return results;
}

// Closes a player's currently-open ownership period and, if there's a new
// owner, opens a fresh one for them starting now. `newUid: null` means the
// player is going back to the undrafted pool (no new period opened).
function closeAndOpenOwnership(updates, code, lobby, playerId, newUid, now) {
  const periods = getOwnershipPeriods(lobby, playerId);
  const openIdx = periods.findIndex(p => p.to === null);
  const logPath = `lobbies/${code}/ownershipLog/${playerId}`;

  if (openIdx >= 0) {
    updates[`${logPath}/p${openIdx}/to`] = now;
  }
  if (newUid) {
    updates[`${logPath}/p${periods.length}`] = { uid: newUid, from: now, to: null };
  }
}

// Advances the turn pointer, rolling into the next round or closing
// trading entirely once tradeRounds is exhausted. Resets the reject
// counter for whoever's turn it becomes.
async function advanceTurn(code, lobby) {
  const order = lobby.tradeOrder || [];
  let idx   = (lobby.currentTurnIndex ?? 0) + 1;
  let round = lobby.currentRound || 1;

  if (idx >= order.length) {
    idx = 0;
    round += 1;
  }

  if (round > (lobby.tradeRounds || 1)) {
    await update(ref(db, `lobbies/${code}`), {
      tradingEnabled:  false,
      tradingClosedAt: Date.now(),
    });
    return;
  }

  await update(ref(db, `lobbies/${code}`), {
    currentRound:     round,
    currentTurnIndex: idx,
    currentTurnUid:   order[idx],
    attemptsThisTurn: 0,
  });
}

// Host starts (or restarts) the trading phase. On a true first start this
// also seeds the roster map + ownership log from the current draft picks;
// on a restart (trading was closed, host reopens it) that history is left
// alone and only the order/round counters reset.
export async function startTrading({ code, rounds, matchData, tournamentData }) {
  const lobbyRef = ref(db, `lobbies/${code}`);
  const snap  = await get(lobbyRef);
  const lobby = snap.val();
  if (!lobby) throw new Error("Lobby not found.");

  const order = computeTradeOrder(lobby, matchData, tournamentData);
  if (order.length === 0) throw new Error("No active managers to trade.");

  const updates = {
    [`lobbies/${code}/tradingEnabled`]:   true,
    [`lobbies/${code}/tradeRounds`]:      rounds,
    [`lobbies/${code}/currentRound`]:     1,
    [`lobbies/${code}/tradeOrder`]:       order,
    [`lobbies/${code}/currentTurnIndex`]: 0,
    [`lobbies/${code}/currentTurnUid`]:   order[0],
    [`lobbies/${code}/attemptsThisTurn`]: 0,
    [`lobbies/${code}/tradingStartedAt`]: Date.now(),
  };

  if (!lobby.roster) {
    const roster = {};
    const ownershipLog = {};
    Object.values(lobby.picks || {}).forEach(pk => {
      roster[pk.playerId] = pk.byUid;
      ownershipLog[pk.playerId] = { p0: { uid: pk.byUid, from: 0, to: null } };
    });
    updates[`lobbies/${code}/roster`]        = roster;
    updates[`lobbies/${code}/ownershipLog`]  = ownershipLog;
  }

  await update(ref(db), updates);
}

// Host can manually close trading at any point, independent of rounds.
export async function closeTrading({ code }) {
  await update(ref(db, `lobbies/${code}`), {
    tradingEnabled:  false,
    tradingClosedAt: Date.now(),
  });
}

// Voluntary self-pass (requestingUid must be the current turn holder) or
// host force-pass (isHost: true bypasses the turn check).
export async function passTurn({ code, requestingUid, isHost }) {
  const snap  = await get(ref(db, `lobbies/${code}`));
  const lobby = snap.val();
  if (!lobby || !lobby.tradingEnabled) return;
  if (!isHost && requestingUid !== lobby.currentTurnUid) {
    throw new Error("It's not your turn.");
  }
  await advanceTurn(code, lobby);
}

// Proposes a manager-vs-manager 1-for-1 trade. Must be the proposer's
// turn, and they can only have one pending offer out at a time.
export async function proposeTrade({ code, fromUid, fromName, toUid, toName, offerPlayerId, offerName, requestPlayerId, requestName }) {
  const snap  = await get(ref(db, `lobbies/${code}`));
  const lobby = snap.val();
  if (!lobby || !lobby.tradingEnabled) throw new Error("Trading isn't open.");
  if (lobby.currentTurnUid !== fromUid) throw new Error("It's not your turn.");

  const openTrade = Object.values(lobby.trades || {}).find(
    t => t.fromUid === fromUid && t.status === "pending"
  );
  if (openTrade) throw new Error("You already have a pending offer out — wait for a response.");

  const roster = buildRosterMap(lobby);
  if (roster[offerPlayerId] !== fromUid) throw new Error("You don't own that player.");
  if (roster[requestPlayerId] !== toUid) throw new Error("They don't own that player.");

  const newRef = push(ref(db, `lobbies/${code}/trades`));
  await set(newRef, {
    type: "player-player",
    fromUid, fromName, toUid, toName,
    offerPlayerId, offerName, requestPlayerId, requestName,
    status: "pending",
    round: lobby.currentRound || 1,
    proposedAt: Date.now(),
  });
}

// The recipient of a pending trade accepts or rejects it.
export async function respondTrade({ code, tradeId, uid, accept }) {
  const lobbyRef = ref(db, `lobbies/${code}`);
  const snap  = await get(lobbyRef);
  const lobby = snap.val();
  if (!lobby) throw new Error("Lobby not found.");
  const trade = lobby.trades?.[tradeId];
  if (!trade || trade.status !== "pending") throw new Error("This trade is no longer pending.");
  if (trade.toUid !== uid) throw new Error("This trade isn't addressed to you.");

  if (!accept) {
    const attempts = (lobby.attemptsThisTurn || 0) + 1;
    await update(ref(db), {
      [`lobbies/${code}/trades/${tradeId}/status`]:     "rejected",
      [`lobbies/${code}/trades/${tradeId}/resolvedAt`]: Date.now(),
    });
    if (attempts >= 3) {
      const freshSnap = await get(lobbyRef);
      await advanceTurn(code, freshSnap.val());
    } else {
      await update(ref(db, `lobbies/${code}`), { attemptsThisTurn: attempts });
    }
    return;
  }

  const now = Date.now();
  const updates = {
    [`lobbies/${code}/trades/${tradeId}/status`]:        "completed",
    [`lobbies/${code}/trades/${tradeId}/resolvedAt`]:    now,
    [`lobbies/${code}/roster/${trade.offerPlayerId}`]:   trade.toUid,
    [`lobbies/${code}/roster/${trade.requestPlayerId}`]: trade.fromUid,
  };
  closeAndOpenOwnership(updates, code, lobby, trade.offerPlayerId,   trade.toUid,   now);
  closeAndOpenOwnership(updates, code, lobby, trade.requestPlayerId, trade.fromUid, now);

  await update(ref(db), updates);
  const freshSnap = await get(lobbyRef);
  await advanceTurn(code, freshSnap.val());
}

// Instant, no-approval trade: give up one of your players to take an
// undrafted one. Must be the acting manager's turn. `givePlayer` /
// `takePlayer` are { id, name } pairs.
export async function undraftedTrade({ code, uid, givePlayer, takePlayer }) {
  const lobbyRef = ref(db, `lobbies/${code}`);
  const snap  = await get(lobbyRef);
  const lobby = snap.val();
  if (!lobby || !lobby.tradingEnabled) throw new Error("Trading isn't open.");
  if (lobby.currentTurnUid !== uid) throw new Error("It's not your turn.");

  const roster = buildRosterMap(lobby);
  if (roster[givePlayer.id] !== uid) throw new Error("You don't own that player.");
  if (roster[takePlayer.id]) throw new Error("That player has already been taken.");

  const now = Date.now();
  const updates = {
    [`lobbies/${code}/roster/${givePlayer.id}`]: null, // back to the undrafted pool
    [`lobbies/${code}/roster/${takePlayer.id}`]: uid,
  };

  const newRef = push(ref(db, `lobbies/${code}/trades`));
  updates[`lobbies/${code}/trades/${newRef.key}`] = {
    type: "player-undrafted",
    fromUid: uid,
    givePlayerId: givePlayer.id, givePlayerName: givePlayer.name,
    takePlayerId: takePlayer.id, takePlayerName: takePlayer.name,
    status: "completed",
    round: lobby.currentRound || 1,
    proposedAt: now,
    resolvedAt: now,
  };

  closeAndOpenOwnership(updates, code, lobby, givePlayer.id, null, now);
  closeAndOpenOwnership(updates, code, lobby, takePlayer.id, uid,  now);

  await update(ref(db), updates);
  const freshSnap = await get(lobbyRef);
  await advanceTurn(code, freshSnap.val());
}
>>>>>>> Stashed changes
