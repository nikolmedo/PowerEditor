import type { JobError, JobEvent, JobKind, JobStatus } from "../api/types";

/** The stages each job reports, in the order they run (see the backend pipelines). */
export const JOB_STAGES: Record<JobKind, readonly string[]> = {
  analyze: ["ingest", "transcribe", "vad", "segments", "loudness", "color", "takes", "draft"],
  render: ["audio", "render", "final-pass"],
  export_subtitles: ["subtitles"],
  whisper_model: ["download"],
};
const KNOWN_STAGES = new Set(Object.values(JOB_STAGES).flat());

export const isTerminal = (status: JobStatus) =>
  status === "succeeded" || status === "failed" || status === "cancelled";

/** Per-source stages are named `<stage>-<source id>`; the UI shows one row per stage. */
export function stageFamily(stage: string): string {
  if (KNOWN_STAGES.has(stage)) return stage;
  const prefix = stage.split("-")[0] ?? stage;
  return KNOWN_STAGES.has(prefix) ? prefix : stage;
}

export interface JobProgress {
  jobId: string;
  status: JobStatus;
  /** Stage family running now (or where the job stopped). */
  current: string | null;
  fraction: number;
  /** Stage families that finished, in the order they finished. */
  done: string[];
  error: JobError | null;
  result: Record<string, unknown> | null;
}

export function initialProgress(jobId: string): JobProgress {
  return {
    jobId,
    status: "queued",
    current: null,
    fraction: 0,
    done: [],
    error: null,
    result: null,
  };
}

/** Fold one event into the progress. Events of other jobs or after the end change nothing. */
export function reduceJob(state: JobProgress, event: JobEvent): JobProgress {
  if (event.jobId !== state.jobId || isTerminal(state.status)) return state;
  if (isTerminal(event.status)) {
    return { ...state, status: event.status, error: event.error, result: event.result };
  }
  const family = event.stage === null ? state.current : stageFamily(event.stage);
  const moved = state.current !== null && family !== state.current;
  const done = moved && !state.done.includes(state.current as string);
  return {
    ...state,
    status: event.status,
    current: family,
    fraction: event.fraction,
    done: done ? [...state.done, state.current as string] : state.done,
  };
}

export type StageState = "done" | "active" | "failed" | "pending";

export interface StageRow {
  stage: string;
  state: StageState;
  fraction: number;
}

/** One row per stage of `kind`, plus any stage the job reported that is not listed. */
export function stageRows(progress: JobProgress, kind: JobKind): StageRow[] {
  const seen = [...progress.done, ...(progress.current ? [progress.current] : [])];
  const stages = [
    ...JOB_STAGES[kind],
    ...seen.filter((stage) => !JOB_STAGES[kind].includes(stage)),
  ];
  return stages.map((stage) => {
    if (progress.status === "succeeded") return { stage, state: "done", fraction: 1 };
    if (stage === progress.current) {
      const state = isTerminal(progress.status) ? "failed" : "active";
      return { stage, state, fraction: progress.fraction };
    }
    if (progress.done.includes(stage)) return { stage, state: "done", fraction: 1 };
    return { stage, state: "pending", fraction: 0 };
  });
}
