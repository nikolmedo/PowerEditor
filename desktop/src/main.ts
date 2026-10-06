/**
 * PowerEditor desktop shell: start the engine (sidecar), then show its web app in a locked
 * down window. The window only ever loads the sidecar's loopback origin; any other link opens
 * in the default browser when its site is on the allowlist, and is dropped otherwise.
 */
import { app, BrowserWindow, dialog, Menu, session, shell, type WebContents } from "electron";
import type { ChildProcess } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { aboutPanelOptions, APP_NAME, applicationMenuTemplate } from "./about";
import { translator, type Translate } from "./messages";
import { isAllowedExternal, isAppUrl } from "./policy";
import {
  SidecarStartError,
  awaitReady,
  killTree,
  sidecarCommand,
  startSidecar,
  type Ready,
} from "./sidecar";
import { showSplash } from "./splash";
import { rememberWindowState, savedWindowOptions } from "./windowState";

const READY_TIMEOUT_S = 90;
/** Permissions the web app may use; everything else (camera, notifications, ...) is denied. */
const ALLOWED_PERMISSIONS = new Set(["fullscreen", "clipboard-sanitized-write"]);

app.setName(APP_NAME);
app.setPath("userData", path.join(app.getPath("appData"), APP_NAME));
const logDir = path.join(app.getPath("userData"), "logs");
const repoRoot = path.resolve(__dirname, "..", "..");

let sidecar: ChildProcess | null = null;
let mainWindow: BrowserWindow | null = null;
let quitting = false;

function openLog(name: string): fs.WriteStream {
  fs.mkdirSync(logDir, { recursive: true });
  return fs.createWriteStream(path.join(logDir, name), { flags: "w" });
}

const shellLog = openLog("desktop.log");
const log = (message: string) => shellLog.write(`${new Date().toISOString()} ${message}\n`);

function fail(t: Translate, message: string): void {
  log(`fatal: ${message}`);
  dialog.showErrorBox(t("error.title"), `${message}\n\n${t("error.logHint", { path: logDir })}`);
  app.quit();
}

function startMessage(t: Translate, error: SidecarStartError): string {
  if (error.reason === "timeout") return t("error.timeout", { seconds: error.detail });
  if (error.reason === "spawn") return t("error.spawn", { message: error.detail });
  return t("error.exited", { code: error.detail });
}

/** The engine stopped while the app was open: offer to restart the app or quit. */
async function offerRestart(t: Translate, code: number | null): Promise<void> {
  const { response } = await dialog.showMessageBox({
    type: "error",
    title: t("error.title"),
    message: t("error.stopped", { code: String(code) }),
    detail: t("error.logHint", { path: logDir }),
    buttons: [t("action.restart"), t("action.quit")],
    defaultId: 0,
    cancelId: 1,
    noLink: true,
  });
  if (response === 0) app.relaunch();
  app.quit();
}

/** Start the engine and resolve with its READY line; rejects on exit, error or timeout. */
async function waitForReady(t: Translate): Promise<Ready> {
  const command = sidecarCommand({
    packaged: app.isPackaged,
    resourcesPath: process.resourcesPath,
    repoRoot,
    parentPid: process.pid,
  });
  log(`starting ${command.file} ${command.args.join(" ")} in ${command.cwd}`);
  const child = startSidecar(command);
  sidecar = child;
  const output = openLog("engine.log");
  child.stderr?.pipe(output);
  child.stdout?.setEncoding("utf-8");
  child.stdout?.on("data", (chunk: string) => {
    output.write(chunk.replace(/POWEREDITOR_READY .*/g, "POWEREDITOR_READY <redacted>"));
  });
  try {
    const ready = await awaitReady(child, { timeoutMs: READY_TIMEOUT_S * 1000, kill: killTree });
    child.once("exit", (code) => {
      log(`engine exited with code ${code}`);
      sidecar = null;
      if (!quitting) void offerRestart(t, code);
    });
    return ready;
  } catch (error) {
    sidecar = null;
    if (!(error instanceof SidecarStartError)) throw error;
    log(`engine did not start: ${error.message}`);
    throw new Error(startMessage(t, error), { cause: error });
  }
}

function openExternal(url: string): void {
  if (isAllowedExternal(url)) void shell.openExternal(url);
  else log(`blocked link: ${url}`);
}

function lockDown(contents: WebContents, origin: string): void {
  const guard = (event: Electron.Event, url: string) => {
    if (isAppUrl(url, origin)) return;
    event.preventDefault();
    openExternal(url);
  };
  contents.on("will-navigate", guard);
  contents.on("will-redirect", guard);
  contents.setWindowOpenHandler(({ url }) => {
    openExternal(url);
    return { action: "deny" };
  });
}

function createMainWindow(ready: Ready, splash: BrowserWindow): void {
  const origin = `http://127.0.0.1:${ready.port}`;
  const stateFile = path.join(app.getPath("userData"), "window-state.json");
  const { bounds, maximized } = savedWindowOptions(stateFile);
  const window = new BrowserWindow({
    ...bounds,
    minWidth: 960,
    minHeight: 600,
    show: false,
    title: APP_NAME,
    backgroundColor: "#1a1c1f",
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webviewTag: false,
      spellcheck: false,
    },
  });
  mainWindow = window;
  lockDown(window.webContents, origin);
  rememberWindowState(window, stateFile);
  window.once("ready-to-show", () => {
    if (maximized) window.maximize();
    window.show();
    splash.destroy();
  });
  window.on("closed", () => {
    mainWindow = null;
  });
  // The bootstrap URL sets the session cookie and redirects to "/".
  void window.loadURL(`${origin}/?token=${encodeURIComponent(ready.token)}`);
}

async function start(): Promise<void> {
  const t = translator(app.getLocale());
  app.setAboutPanelOptions(aboutPanelOptions(app.getVersion()));
  Menu.setApplicationMenu(Menu.buildFromTemplate(applicationMenuTemplate(t("menu.help"))));
  session.defaultSession.setPermissionRequestHandler((_contents, permission, callback) =>
    callback(ALLOWED_PERMISSIONS.has(permission)),
  );
  app.on("web-contents-created", (_event, contents) => {
    contents.on("will-attach-webview", (event) => event.preventDefault());
  });
  if (!app.isPackaged && !fs.existsSync(path.join(repoRoot, "web", "dist", "index.html"))) {
    fail(t, t("error.webMissing"));
    return;
  }
  const splash = showSplash(t("splash.starting"));
  try {
    const ready = await waitForReady(t);
    log(`engine ready on port ${ready.port}`);
    createMainWindow(ready, splash);
  } catch (error) {
    splash.destroy();
    fail(t, error instanceof Error ? error.message : String(error));
  }
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  });
  app.on("window-all-closed", () => app.quit());
  app.on("will-quit", (event) => {
    const child = sidecar;
    if (!child || child.exitCode !== null) return;
    quitting = true;
    event.preventDefault();
    sidecar = null;
    log("stopping the engine");
    void killTree(child).finally(() => app.quit());
  });
  void app.whenReady().then(start);
}
