import { Router } from 'express';
import * as sec from './security.js';

export const authRouter = Router();

authRouter.get('/status', (req, res) => {
  const token = sec.bearerToken(req);
  res.json({
    configured: sec.isConfigured(),
    unlocked: Boolean(token && sec.touchSession(token)),
    lockoutMs: sec.lockoutRemaining(),
  });
});

authRouter.post('/setup', (req, res) => {
  if (sec.isConfigured()) {
    return res.status(409).json({ error: 'A PIN is already set. Change it from Settings instead.' });
  }
  const problem = sec.validatePinFormat(req.body?.pin);
  if (problem) return res.status(400).json({ error: problem });

  sec.setPin(req.body.pin);
  return res.status(201).json({ token: sec.createSession() });
});

authRouter.post('/unlock', (req, res) => {
  const wait = sec.lockoutRemaining();
  if (wait > 0) {
    return res.status(429).json({
      error: `Too many attempts. Try again in ${Math.ceil(wait / 1000)}s.`,
      lockoutMs: wait,
    });
  }

  if (!sec.verifyPin(req.body?.pin)) {
    const next = sec.lockoutRemaining();
    return res.status(401).json({
      error: next > 0 ? `Wrong PIN. Locked out for ${Math.ceil(next / 1000)}s.` : 'Wrong PIN.',
      lockoutMs: next,
    });
  }

  return res.json({ token: sec.createSession() });
});

authRouter.post('/lock', (req, res) => {
  const token = sec.bearerToken(req);
  if (token) sec.revokeSession(token);
  res.status(204).end();
});

authRouter.post('/change', (req, res) => {
  const token = sec.bearerToken(req);
  if (!token || !sec.touchSession(token)) return res.status(401).json({ error: 'Locked' });

  if (!sec.verifyPin(req.body?.currentPin)) {
    return res.status(401).json({ error: 'Current PIN is wrong.' });
  }
  const problem = sec.validatePinFormat(req.body?.newPin);
  if (problem) return res.status(400).json({ error: problem });

  sec.setPin(req.body.newPin);
  // Every other session is stale once the PIN changes.
  sec.revokeAllSessions();
  return res.json({ token: sec.createSession() });
});
