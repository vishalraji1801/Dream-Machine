import { randomBytes, scryptSync, timingSafeEqual } from 'node:crypto';
import { db } from './db.js';

const SCRYPT_KEYLEN = 64;
const SESSION_IDLE_MS = 30 * 60 * 1000; // server-side backstop; the UI locks sooner
const MAX_ATTEMPTS = 5;
const LOCKOUT_BASE_MS = 15_000;

const getSetting = db.prepare('SELECT value FROM app_settings WHERE key = ?');
const putSetting = db.prepare(`
  INSERT INTO app_settings (key, value) VALUES (@key, @value)
  ON CONFLICT(key) DO UPDATE SET value = excluded.value
`);

/** Sessions live in memory only, so closing the app always re-locks it. */
const sessions = new Map();
let failedAttempts = 0;
let lockedOutUntil = 0;

function read(key) {
  return getSetting.get(key)?.value ?? null;
}

export function isConfigured() {
  return read('pin_hash') !== null;
}

function hash(pin, salt) {
  return scryptSync(pin.normalize('NFKC'), salt, SCRYPT_KEYLEN);
}

export function validatePinFormat(pin) {
  if (typeof pin !== 'string') return 'PIN must be text';
  const trimmed = pin.trim();
  if (trimmed.length < 4) return 'Use at least 4 characters';
  if (trimmed.length > 64) return 'Use at most 64 characters';
  return null;
}

export function setPin(pin) {
  const salt = randomBytes(16);
  putSetting.run({ key: 'pin_salt', value: salt.toString('hex') });
  putSetting.run({ key: 'pin_hash', value: hash(pin.trim(), salt).toString('hex') });
  failedAttempts = 0;
  lockedOutUntil = 0;
}

/** Remaining cooldown in ms after too many wrong guesses, or 0. */
export function lockoutRemaining() {
  return Math.max(lockedOutUntil - Date.now(), 0);
}

export function verifyPin(pin) {
  if (lockoutRemaining() > 0) return false;

  const saltHex = read('pin_salt');
  const expectedHex = read('pin_hash');
  if (!saltHex || !expectedHex) return false;

  const expected = Buffer.from(expectedHex, 'hex');
  const actual = hash(String(pin ?? '').trim(), Buffer.from(saltHex, 'hex'));

  const ok = actual.length === expected.length && timingSafeEqual(actual, expected);

  if (ok) {
    failedAttempts = 0;
    lockedOutUntil = 0;
  } else {
    failedAttempts += 1;
    if (failedAttempts >= MAX_ATTEMPTS) {
      // Back off exponentially so a 4-digit PIN can't be ground through.
      const over = failedAttempts - MAX_ATTEMPTS;
      lockedOutUntil = Date.now() + LOCKOUT_BASE_MS * 2 ** Math.min(over, 6);
    }
  }
  return ok;
}

export function createSession() {
  const token = randomBytes(32).toString('hex');
  sessions.set(token, { lastSeen: Date.now() });
  return token;
}

export function touchSession(token) {
  const s = sessions.get(token);
  if (!s) return false;
  if (Date.now() - s.lastSeen > SESSION_IDLE_MS) {
    sessions.delete(token);
    return false;
  }
  s.lastSeen = Date.now();
  return true;
}

export function revokeSession(token) {
  sessions.delete(token);
}

export function revokeAllSessions() {
  sessions.clear();
}

export function bearerToken(req) {
  const header = req.get('authorization') ?? '';
  return header.startsWith('Bearer ') ? header.slice(7) : null;
}

/**
 * Gate for every data route. The server is loopback-only, but any process on the
 * machine can still reach the port — without this the lock screen would be cosmetic.
 */
export function requireUnlocked(req, res, next) {
  if (!isConfigured()) return next(); // no PIN set yet: app is open by design
  const token = bearerToken(req);
  if (token && touchSession(token)) return next();
  return res.status(401).json({ error: 'Locked', locked: true });
}
