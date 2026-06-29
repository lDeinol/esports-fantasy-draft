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
// Valorant-specific scoring weights
export const SCORING = {
  weights: {
    rating: 40,
    kd:     25,
    acs:    0.15,
    adr:    0.10,
    kpr:    10,
    cl:     0.20,
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

// ── Firebase Lobby Helpers ───────────────────────────────────

// Create a new lobby in Firebase
export async function createLobby({ code, hostUid, hostName, format, tournamentId }) {
  const lobbyRef = ref(db, `lobbies/${code}`);
  await set(lobbyRef, {
    code,
    format,
    tournamentId:     tournamentId || null,
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

// Add a player to an existing lobby
export async function joinLobby({ code, uid, name }) {
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

// ── Utility ──────────────────────────────────────────────────
export function formatCurrency(n) {
  return `$${Math.round(n)}`;
}

export function el(id) {
  return document.getElementById(id);
}
