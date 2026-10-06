import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import { describe, expect, it, vi } from "vitest";
import { releaseRequest, type OpenRequest, type RedirectingRequest } from "../src/releaseRequest";

class FakeRequest extends EventEmitter implements RedirectingRequest {
  followRedirect = vi.fn();
  abort = vi.fn();
  end = vi.fn();
}

class FakeMessage extends PassThrough {
  constructor(
    readonly statusCode: number,
    readonly headers: Record<string, string | string[]> = {},
    readonly statusMessage = "",
  ) {
    super();
  }
}

function opener() {
  const request = new FakeRequest();
  const open = vi.fn<OpenRequest>(() => request);
  return { request, open };
}

const allowOnly =
  (allowed: string) =>
  (url: string): boolean =>
    url === allowed;

describe("releaseRequest", () => {
  it("asks for manual redirects and resolves with the response and its body", async () => {
    const { request, open } = opener();
    const response = releaseRequest(open)("https://github.com/a", {
      signal: new AbortController().signal,
      allowRedirect: () => false,
    });
    const message = new FakeMessage(200, { "content-length": "5", "x-list": ["a", "b"] });
    request.emit("response", message);
    message.end("hello");

    const answer = await response;
    expect(open).toHaveBeenCalledWith({ url: "https://github.com/a", redirect: "manual" });
    expect(request.end).toHaveBeenCalled();
    expect(answer.status).toBe(200);
    expect(answer.headers.get("content-length")).toBe("5");
    expect(answer.headers.get("x-list")).toBe("a, b");
    expect(await answer.text()).toBe("hello");
  });

  it("follows a redirect the policy allows", async () => {
    const { request, open } = opener();
    const storage = "https://objects.githubusercontent.com/x";
    const response = releaseRequest(open)("https://github.com/a", {
      signal: new AbortController().signal,
      allowRedirect: allowOnly(storage),
    });

    request.emit("redirect", 302, "GET", storage, {});
    expect(request.followRedirect).toHaveBeenCalledTimes(1);
    const message = new FakeMessage(200);
    request.emit("response", message);
    message.end();

    expect((await response).status).toBe(200);
  });

  it("aborts and rejects on a redirect the policy refuses", async () => {
    const { request, open } = opener();
    const response = releaseRequest(open)("https://github.com/a", {
      signal: new AbortController().signal,
      allowRedirect: allowOnly("https://objects.githubusercontent.com/x"),
    });

    request.emit("redirect", 302, "GET", "https://evil.example/x", {});

    await expect(response).rejects.toThrow("redirect refused: evil.example");
    expect(request.followRedirect).not.toHaveBeenCalled();
    expect(request.abort).toHaveBeenCalled();
  });

  it("rejects on a request error", async () => {
    const { request, open } = opener();
    const response = releaseRequest(open)("https://github.com/a", {
      signal: new AbortController().signal,
      allowRedirect: () => false,
    });

    request.emit("error", new Error("net::ERR_CONNECTION_RESET"));

    await expect(response).rejects.toThrow("net::ERR_CONNECTION_RESET");
  });

  it("aborts the request when the signal fires", async () => {
    const { request, open } = opener();
    const controller = new AbortController();
    const response = releaseRequest(open)("https://github.com/a", {
      signal: controller.signal,
      allowRedirect: () => false,
    });

    controller.abort(new Error("timed out"));

    await expect(response).rejects.toThrow("timed out");
    expect(request.abort).toHaveBeenCalled();
  });
});
