'use strict';

/**
 * The only bridge between the renderer and Node.
 *
 * Context isolation is on, so the renderer gets exactly these functions and
 * nothing else - no fs, no child_process, no ipcRenderer.
 */

const { contextBridge, ipcRenderer } = require('electron');
const PACKAGE_METADATA = require('./package.json');

const events = ['progress', 'phase', 'log', 'activity', 'done', 'failed', 'cancelled'];

contextBridge.exposeInMainWorld('clipify', {
  version: process.env.npm_package_version || '2.0.0',
  qa: Boolean(PACKAGE_METADATA.clipifyQaInstallSlug),

  detect: (options) => ipcRenderer.invoke('setup:detect', options || {}),
  musicTracks: () => ipcRenderer.invoke('setup:music'),
  browse: () => ipcRenderer.invoke('setup:browse'),
  start: (options) => ipcRenderer.invoke('setup:start', options),
  cancel: () => ipcRenderer.invoke('setup:cancel'),
  retry: (phaseId, options) => ipcRenderer.invoke('setup:retry', { phaseId, options }),
  launch: () => ipcRenderer.invoke('setup:launch'),
  openFolder: (target) => ipcRenderer.invoke('setup:openFolder', target),
  openLog: () => ipcRenderer.invoke('setup:openLog'),
  openExternal: (url) => ipcRenderer.invoke('setup:openExternal', url),
  window: (action) => ipcRenderer.invoke('setup:window', action),
  state: () => ipcRenderer.invoke('setup:state'),
  quit: () => ipcRenderer.invoke('setup:quit'),
  rendererReady: () => ipcRenderer.invoke('setup:renderer-ready'),
  rendererError: (message) => ipcRenderer.invoke('setup:renderer-error', String(message || 'Unknown startup error')),

  on: (event, handler) => {
    if (!events.includes(event)) return () => {};
    const listener = (_e, payload) => handler(payload);
    ipcRenderer.on(`setup:${event}`, listener);
    return () => ipcRenderer.removeListener(`setup:${event}`, listener);
  },
});
