import { ApiError } from "./client";
import { api } from "./endpoints";
import type { JobEvent, JobInfo } from "./types";

export const TERMINAL_STATUSES: ReadonlySet<string> = new Set(["succeeded", "failed", "cancelled"]);
const POLL_MS = 1000;
/** Consecutive failed polls (server unreachable) before the job is reported as lost. */
const MAX_POLL_FAILURES = 10;

export function jobEventsUrl(jobId: string, location: Location = window.location): string {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${location.host}/api/jobs/${encodeURIComponent(jobId)}/events`;
}

export function eventFromInfo(info: JobInfo): JobEvent {
  const { id, status, stage, fraction, message, error, result } = info;
  return { jobId: id, status, stage, fraction, message, error, result };
}

function lostEvent(jobId: string, error: ApiError): JobEvent {
  return {
    jobId,
    status: "failed",
    stage: null,
    fraction: 0,
    message: "",
    error: { code: error.code ?? "network", message: error.message },
    result: null,
  };
}

export interface WatchOptions {
  pollMs?: number;
  fetchJob?: (jobId: string) => Promise<JobInfo>;
}

/**
 * Follow a job's events until its terminal status. The WebSocket streams them; if it drops
 * before the end (server restart, proxy, sleep), the job is polled over HTTP instead.
 * Returns a function that stops listening.
 */
export function watchJob(
  jobId: string,
  onEvent: (event: JobEvent) => void,
  { pollMs = POLL_MS, fetchJob = api.job }: WatchOptions = {},
): () => void {
  let finished = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let failures = 0;

  const deliver = (event: JobEvent) => {
    if (finished) return;
    onEvent(event);
    if (TERMINAL_STATUSES.has(event.status)) finished = true;
  };

  const poll = async () => {
    try {
      deliver(eventFromInfo(await fetchJob(jobId)));
      failures = 0;
    } catch (caught) {
      const error = caught instanceof ApiError ? caught : new ApiError(0, null, String(caught));
      failures += 1;
      if (error.status === 404 || failures >= MAX_POLL_FAILURES) deliver(lostEvent(jobId, error));
    }
    if (!finished) timer = setTimeout(() => void poll(), pollMs);
  };

  const socket = new WebSocket(jobEventsUrl(jobId));
  socket.onmessage = (message: MessageEvent<string>) => {
    deliver(JSON.parse(message.data) as JobEvent);
    if (finished) socket.close();
  };
  socket.onclose = () => {
    if (!finished) timer = setTimeout(() => void poll(), pollMs);
  };

  return () => {
    finished = true;
    clearTimeout(timer);
    socket.close();
  };
}
