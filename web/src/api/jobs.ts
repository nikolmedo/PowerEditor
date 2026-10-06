import { ApiError } from "./client";
import { api } from "./endpoints";
import type { JobEvent, JobInfo } from "./types";

export const TERMINAL_STATUSES: ReadonlySet<string> = new Set(["succeeded", "failed", "cancelled"]);
const POLL_MS = 1000;
/** A socket that sends nothing for this long is treated as lost (half-open, sleeping proxy). */
const STALL_MS = 30_000;
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
  stallMs?: number;
  fetchJob?: (jobId: string) => Promise<JobInfo>;
}

/**
 * Follow a job's events until its terminal status. The WebSocket streams them; if it drops
 * before the end (server restart, proxy, sleep) or goes silent for `stallMs`, the job is
 * polled over HTTP instead.
 * Returns a function that stops listening.
 */
export function watchJob(
  jobId: string,
  onEvent: (event: JobEvent) => void,
  { pollMs = POLL_MS, stallMs = STALL_MS, fetchJob = api.job }: WatchOptions = {},
): () => void {
  let finished = false;
  let polling = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let stallTimer: ReturnType<typeof setTimeout> | undefined;
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

  const switchToPolling = (delayMs: number) => {
    clearTimeout(stallTimer);
    if (finished || polling) return;
    polling = true;
    timer = setTimeout(() => void poll(), delayMs);
  };

  const socket = new WebSocket(jobEventsUrl(jobId));
  const watchForStall = () => {
    clearTimeout(stallTimer);
    stallTimer = setTimeout(() => {
      socket.close();
      switchToPolling(0);
    }, stallMs);
  };
  socket.onmessage = (message: MessageEvent<string>) => {
    deliver(JSON.parse(message.data) as JobEvent);
    if (finished) {
      clearTimeout(stallTimer);
      socket.close();
    } else {
      watchForStall();
    }
  };
  socket.onclose = () => switchToPolling(pollMs);
  watchForStall();

  return () => {
    finished = true;
    clearTimeout(timer);
    clearTimeout(stallTimer);
    socket.close();
  };
}
