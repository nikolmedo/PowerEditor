import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../src/api/client";
import { watchJob } from "../src/api/jobs";
import type { JobEvent, JobInfo } from "../src/api/types";
import { useResource } from "../src/ui/useResource";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => (resolve = done));
  return { promise, resolve };
}

describe("useResource", () => {
  it("keeps the newest load when an older one answers last", async () => {
    const first = deferred<string>();
    const second = deferred<string>();
    const { result, rerender } = renderHook(({ load }) => useResource(load), {
      initialProps: { load: () => first.promise },
    });
    rerender({ load: () => second.promise });

    await act(async () => second.resolve("new"));
    await act(async () => first.resolve("old"));

    expect(result.current.data).toBe("new");
    expect(result.current.loading).toBe(false);
  });
});

class FakeSocket {
  static last: FakeSocket | null = null;
  onmessage: ((message: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  closed = false;
  constructor(readonly url: string) {
    FakeSocket.last = this;
  }
  close() {
    this.closed = true;
  }
  emit(event: Partial<JobEvent>) {
    this.onmessage?.({ data: JSON.stringify(event) });
  }
}

const job = (overrides: Partial<JobInfo>): JobInfo => ({
  id: "j1",
  kind: "render",
  status: "running",
  stage: "render",
  fraction: 0.5,
  message: "",
  error: null,
  result: null,
  ...overrides,
});

describe("watchJob", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("falls back to polling when the socket drops before the job ends", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeSocket);
    const fetchJob = vi
      .fn()
      .mockResolvedValueOnce(job({ fraction: 0.7 }))
      .mockResolvedValueOnce(job({ status: "succeeded", fraction: 1, result: { file: "a.mp4" } }));
    const events: JobEvent[] = [];
    watchJob("j1", (event) => events.push(event), { pollMs: 100, fetchJob });

    FakeSocket.last?.emit({ jobId: "j1", status: "running", stage: "render", fraction: 0.2 });
    FakeSocket.last?.onclose?.();
    await vi.advanceTimersByTimeAsync(250);

    expect(events.map((event) => [event.status, event.fraction])).toEqual([
      ["running", 0.2],
      ["running", 0.7],
      ["succeeded", 1],
    ]);
    expect(events[2]?.result).toEqual({ file: "a.mp4" });
    expect(fetchJob).toHaveBeenCalledTimes(2);
  });

  it("reports a job the server no longer knows as failed", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeSocket);
    const fetchJob = vi.fn().mockRejectedValue(new ApiError(404, "job_not_found", "gone"));
    const events: JobEvent[] = [];
    watchJob("j1", (event) => events.push(event), { pollMs: 100, fetchJob });

    FakeSocket.last?.onclose?.();
    await vi.advanceTimersByTimeAsync(150);

    expect(events).toHaveLength(1);
    expect([events[0]?.status, events[0]?.error?.code]).toEqual(["failed", "job_not_found"]);
  });

  it("stops without polling once the caller stops listening", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeSocket);
    const fetchJob = vi.fn();
    const stop = watchJob("j1", () => undefined, { pollMs: 100, fetchJob });

    stop();
    FakeSocket.last?.onclose?.();
    await vi.advanceTimersByTimeAsync(300);

    expect(FakeSocket.last?.closed).toBe(true);
    expect(fetchJob).not.toHaveBeenCalled();
  });
});
