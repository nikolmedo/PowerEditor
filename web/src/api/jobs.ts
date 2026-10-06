import type { JobEvent } from "./types";

const TERMINAL = new Set(["succeeded", "failed", "cancelled"]);

export function jobEventsUrl(jobId: string, location: Location = window.location): string {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${location.host}/api/jobs/${encodeURIComponent(jobId)}/events`;
}

/** Follow a job's events until its terminal status. Returns a function that stops listening. */
export function watchJob(jobId: string, onEvent: (event: JobEvent) => void): () => void {
  const socket = new WebSocket(jobEventsUrl(jobId));
  socket.onmessage = (message: MessageEvent<string>) => {
    const event = JSON.parse(message.data) as JobEvent;
    onEvent(event);
    if (TERMINAL.has(event.status)) socket.close();
  };
  return () => socket.close();
}
