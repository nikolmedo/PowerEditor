import { BrowserWindow } from "electron";

const BACKGROUND = "#1a1c1f";

function escapeHtml(text: string): string {
  return text.replace(/[&<>"]/g, (char) => `&#${char.charCodeAt(0)};`);
}

/** A small window shown while the engine starts; inline HTML, nothing loaded from anywhere. */
export function showSplash(message: string): BrowserWindow {
  const splash = new BrowserWindow({
    width: 360,
    height: 180,
    frame: false,
    resizable: false,
    movable: true,
    center: true,
    backgroundColor: BACKGROUND,
    webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false },
  });
  const html = `<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<style>
  body { margin: 0; height: 100vh; display: grid; place-content: center; gap: 14px;
    background: ${BACKGROUND}; color: #e8e6e3; font: 15px "Segoe UI", system-ui, sans-serif; }
  .bar { width: 220px; height: 3px; background: #2e3238; overflow: hidden; }
  .bar::after { content: ""; display: block; width: 40%; height: 100%; background: #e9a23b;
    animation: slide 1.2s ease-in-out infinite; }
  @keyframes slide { from { transform: translateX(-100%); } to { transform: translateX(250%); } }
</style></head><body><span>${escapeHtml(message)}</span><div class="bar"></div></body></html>`;
  void splash.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`);
  return splash;
}
