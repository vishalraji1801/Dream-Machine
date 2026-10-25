const { app, BrowserWindow, Menu, shell, ipcMain, screen } = require('electron');
const path = require('path');

// Keep timers running at full speed when the app is minimized or hidden behind other windows.
// Without these, Chromium slows background timers down and a countdown looks like it stopped.
app.commandLine.appendSwitch('disable-renderer-backgrounding');
app.commandLine.appendSwitch('disable-background-timer-throttling');
app.commandLine.appendSwitch('disable-backgrounding-occluded-windows');

let mainWin = null;
let widgetWin = null;
let widgetOpen = false;         // the widget is showing because a timer's "minimize to widget" button was pressed
let widgetStyle = 'ring';       // 'ring' or 'bars'
let data = { items: [] };
let appliedSize = '';           // the size we last asked for; compared instead of the real bounds, which Windows can round by a pixel

const webPrefs = () => ({
  contextIsolation: true,
  sandbox: true,
  backgroundThrottling: false,
  autoplayPolicy: 'no-user-gesture-required',
  preload: path.join(__dirname, 'preload.js'),
});

function createWindow() {
  const win = new BrowserWindow({
    width: 1100,
    height: 860,
    minWidth: 420,
    minHeight: 560,
    title: 'Streak',
    webPreferences: webPrefs(),
  });
  mainWin = win;
  Menu.setApplicationMenu(null);
  // Reference links open in the default browser, never inside the app window.
  const openExternal = url => { if (/^https?:\/\//i.test(url)) shell.openExternal(url); };
  win.webContents.setWindowOpenHandler(({ url }) => { openExternal(url); return { action: 'deny' }; });
  win.webContents.on('will-navigate', (e, url) => { if (!url.startsWith('file:')) { e.preventDefault(); openExternal(url); } });
  win.on('closed', () => {
    mainWin = null;
    if (widgetWin && !widgetWin.isDestroyed()) widgetWin.destroy();
  });
  win.loadFile(path.join(__dirname, 'index.html'));
}

// ---------- Timer widget: a small always-on-top window, like the Windows Clock timer ----------
const alive = () => widgetWin && !widgetWin.isDestroyed();

function widgetSize() {
  const n = Math.max(data.items.length, 1);
  if (widgetStyle === 'ring') return [Math.max(210, 20 + 112 * Math.min(n, 3)), 232];
  return [300, 30 + 70 * Math.min(n, 4)];
}

// resize while keeping the bottom-right corner where it is, and only when the wanted size really changes
function applySize() {
  if (!alive()) return;
  const [w, h] = widgetSize(), key = w + 'x' + h;
  if (key === appliedSize) return;
  appliedSize = key;
  const b = widgetWin.getBounds();
  widgetWin.setBounds({ x: b.x + b.width - w, y: b.y + b.height - h, width: w, height: h });
}

function showWidget() {
  if (!alive()) {
    const [w, h] = widgetSize(), wa = screen.getPrimaryDisplay().workArea;
    appliedSize = w + 'x' + h;
    widgetWin = new BrowserWindow({
      width: w, height: h,
      x: wa.x + wa.width - w - 16, y: wa.y + wa.height - h - 16,
      frame: false, alwaysOnTop: true, resizable: false, skipTaskbar: true,
      minimizable: false, maximizable: false, fullscreenable: false, show: false,
      title: 'Streak timer',
      webPreferences: webPrefs(),
    });
    widgetWin.setAlwaysOnTop(true, 'floating');
    widgetWin.loadFile(path.join(__dirname, 'widget.html'));
    widgetWin.webContents.on('did-finish-load', () => alive() && widgetWin.webContents.send('timer-update', data));
    widgetWin.once('ready-to-show', () => alive() && widgetWin.showInactive());
    widgetWin.on('closed', () => { widgetWin = null; appliedSize = ''; });
  } else {
    applySize();
    if (!widgetWin.isVisible()) widgetWin.showInactive();
  }
}

function closeWidget() {
  widgetOpen = false;
  if (alive()) widgetWin.hide();
  if (mainWin && !mainWin.isDestroyed()) mainWin.webContents.send('widget-closed');
}

ipcMain.on('timer-state', (e, p) => {
  if (!p || !Array.isArray(p.items)) return;
  const clean = x => ({
    id: String(x.id), name: String(x.name || '').slice(0, 60),
    total: Number(x.total) || 0, remaining: Number(x.remaining) || 0, running: !!x.running, endAt: Number(x.endAt) || 0,
  });
  data = { items: p.items.slice(0, 12).map(clean) };
  if (!widgetOpen) return;
  if (!data.items.length) { closeWidget(); return; }              // everything pinned is finished
  showWidget();
  if (alive() && !widgetWin.webContents.isLoading()) widgetWin.webContents.send('timer-update', data);
});
// The "minimize to widget" button next to a timer: collapse the app to a small floating timer
ipcMain.on('widget-open', () => {
  widgetOpen = true;
  showWidget();
  if (mainWin && !mainWin.isDestroyed()) mainWin.minimize();
});
ipcMain.on('widget-close', closeWidget);
ipcMain.on('widget-style', (e, style) => {
  if (!['ring', 'bars'].includes(style)) return;
  widgetStyle = style; applySize();
});
ipcMain.on('widget-action', (e, d) => {
  if (!d || typeof d.id !== 'string' || !['pause', 'resume', 'reset', 'done'].includes(d.action)) return;
  if (mainWin && !mainWin.isDestroyed()) mainWin.webContents.send('widget-action', { action: d.action, id: d.id });
});
ipcMain.on('focus-main', () => {
  if (!mainWin || mainWin.isDestroyed()) return;
  if (mainWin.isMinimized()) mainWin.restore();
  mainWin.show(); mainWin.focus();
});

app.whenReady().then(createWindow);
app.on('window-all-closed', () => app.quit());
