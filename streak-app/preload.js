// Safe bridge between the app windows and the main process (used by the timer widget).
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('desktop', {
  timerState: payload => ipcRenderer.send('timer-state', payload),
  openWidget: () => ipcRenderer.send('widget-open'),
  closeWidget: () => ipcRenderer.send('widget-close'),
  setStyle: style => ipcRenderer.send('widget-style', style),
  widgetAction: d => ipcRenderer.send('widget-action', d),
  focusMain: () => ipcRenderer.send('focus-main'),
  onTimerUpdate: cb => ipcRenderer.on('timer-update', (_e, p) => cb(p)),
  onWidgetAction: cb => ipcRenderer.on('widget-action', (_e, d) => cb(d)),
  onWidgetClosed: cb => ipcRenderer.on('widget-closed', () => cb()),
});
