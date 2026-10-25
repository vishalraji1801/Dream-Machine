const { app, BrowserWindow, Menu, dialog, shell } = require('electron');
const { copyFileSync, existsSync, mkdirSync } = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

// Single instance: a second launch focuses the existing window instead of
// starting a second server against the same SQLite file.
if (!app.requestSingleInstanceLock()) {
  app.quit();
  process.exit(0);
}

const ROOT = path.join(__dirname, '..');

/*
 * Pin userData explicitly. Electron derives it from the app name, so renaming the
 * product would otherwise point the app at a fresh empty folder and look exactly
 * like total data loss. This path must never change.
 */
app.setPath('userData', path.join(app.getPath('appData'), 'lenden-portfolio-tracker'));

let mainWindow = null;
let server = null;
let checkpoint = () => {};

/** The database lives in userData so an app update never overwrites it. */
function resolveDatabasePath() {
  const userData = app.getPath('userData');
  mkdirSync(userData, { recursive: true });
  const target = path.join(userData, 'lenden.db');

  // One-time pickup of a database created by the old `npm start` workflow.
  const legacy = path.join(ROOT, 'backend', 'data', 'lenden.db');
  if (!existsSync(target) && existsSync(legacy)) {
    try {
      copyFileSync(legacy, target);
    } catch (err) {
      console.error('Could not migrate the existing database:', err);
    }
  }

  return target;
}

async function startBackend() {
  process.env.LENDEN_DB = resolveDatabasePath();

  const appModule = pathToFileURL(path.join(ROOT, 'backend', 'src', 'app.js')).href;
  const { startServer } = await import(appModule);

  const dbModule = pathToFileURL(path.join(ROOT, 'backend', 'src', 'db.js')).href;
  ({ checkpoint } = await import(dbModule));

  return startServer({
    port: 0,
    host: '127.0.0.1',
    distPath: path.join(ROOT, 'frontend', 'dist'),
  });
}

function buildMenu() {
  const template = [
    {
      label: 'File',
      submenu: [
        {
          label: 'Show data folder',
          click: () => shell.showItemInFolder(process.env.LENDEN_DB),
        },
        { type: 'separator' },
        { role: 'quit' },
      ],
    },
    {
      label: 'View',
      submenu: [
        { role: 'reload' },
        { role: 'toggleDevTools' },
        { type: 'separator' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen' },
      ],
    },
    { label: 'Edit', submenu: [{ role: 'cut' }, { role: 'copy' }, { role: 'paste' }, { role: 'selectAll' }] },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function createWindow(port) {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 900,
    minHeight: 600,
    show: false,
    backgroundColor: '#0d0d0d',
    title: 'Personal Finance App',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  mainWindow.once('ready-to-show', () => mainWindow.show());
  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  // Keep external links in the real browser, not in the app shell.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.loadURL(`http://127.0.0.1:${port}/`);
  console.log(`LenDen desktop ready on 127.0.0.1:${port}`);
}

app.on('second-instance', () => {
  if (!mainWindow) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.focus();
});

app.whenReady().then(async () => {
  buildMenu();

  try {
    server = await startBackend();
  } catch (err) {
    dialog.showErrorBox(
      'LenDen Portfolio Tracker could not start',
      `The local data service failed to start.\n\n${err.stack ?? err.message}`,
    );
    app.quit();
    return;
  }

  createWindow(server.address().port);

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow(server.address().port);
  });
});

app.on('window-all-closed', () => {
  app.quit();
});

app.on('quit', () => {
  server?.close();
  checkpoint();
});

// Closing the window is the normal way out, so fold the log in there too rather
// than relying on a clean quit that a forced kill would never reach.
app.on('before-quit', () => checkpoint());
