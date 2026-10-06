import { useEffect, useRef, useState } from "react";
import { watchJob } from "../api/jobs";
import { initialProgress, isTerminal, reduceJob, type JobProgress } from "./jobProgress";

/**
 * Follow `jobId` (null: none) and return its progress. `onEnd` runs once when the job
 * reaches a terminal status; switching to another job starts from a clean state.
 */
export function useJob(
  jobId: string | null,
  onEnd?: (progress: JobProgress) => void,
): JobProgress | null {
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const onEndRef = useRef(onEnd);
  useEffect(() => {
    onEndRef.current = onEnd;
  });

  useEffect(() => {
    if (!jobId) {
      setProgress(null);
      return;
    }
    let state = initialProgress(jobId);
    setProgress(state);
    return watchJob(jobId, (event) => {
      const next = reduceJob(state, event);
      if (next === state) return;
      const ended = isTerminal(next.status) && !isTerminal(state.status);
      state = next;
      setProgress(next);
      if (ended) onEndRef.current?.(next);
    });
  }, [jobId]);

  return progress;
}

export const isRunning = (progress: JobProgress | null): progress is JobProgress =>
  progress !== null && !isTerminal(progress.status);
