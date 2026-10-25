# Streak

A habit tracker with a calendar, streaks, points, chained habits, timers and counters, success/fail ("avoid") habits,
sub-habits, a weekly review, and tips from habit research. It runs as a Windows desktop app (Electron) and as an
installable web app for Android, with optional sign-in and cloud sync through Firebase.

## Run the desktop app

```
cd streak-app
npm install
npm start
```

Build a portable Windows exe: `npm run dist` (output in `dist/`).

## Sign-in, sync and the phone app

See [SETUP.md](SETUP.md) for the free Firebase setup and [PLAY_STORE.md](PLAY_STORE.md) for publishing on Google Play.
Without a Firebase config in `firebase-config.js` the app works fully offline and saves on the device only.

## Files

- `index.html` is the whole app (HTML, CSS and JavaScript).
- `main.js`, `preload.js`, `widget.html` are the desktop shell and the floating timer widget.
- `manifest.webmanifest`, `sw.js`, `icons/` make the web version installable on Android.
- `privacy.html` is the privacy policy page (fill in the placeholders before publishing).
