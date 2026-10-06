/** The version whose update banner the user hid; a newer version shows it again. Storage
 * may be unavailable (private mode, blocked site data), which only means no memory. */
const KEY = "powereditor.dismissedUpdate";

export function dismissedVersion(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function dismissVersion(version: string): void {
  try {
    localStorage.setItem(KEY, version);
  } catch {
    // Nothing to keep it in; the banner comes back on the next start.
  }
}
