/**
 * The updater's HTTP GET on Electron's `net.request` (it follows the system proxy settings).
 *
 * `net.fetch` cannot check redirects: with `redirect: "follow"` it follows every hop without
 * a hook and its `Response` carries no final URL, and with `"manual"` it fails on the first
 * hop. `net.request` in manual mode reports each hop and waits for `followRedirect()`.
 */
import type { EventEmitter } from "node:events";
import { Readable } from "node:stream";
import type { ReleaseRequest } from "./updater";

/** What this module needs of Electron's `ClientRequest`. */
export interface RedirectingRequest extends EventEmitter {
  followRedirect(): void;
  abort(): void;
  end(): void;
}

/** What this module needs of Electron's `IncomingMessage`. */
export interface IncomingResponse extends Readable {
  readonly statusCode: number;
  readonly statusMessage: string;
  readonly headers: Record<string, string | string[]>;
}

export type OpenRequest = (options: { url: string; redirect: "manual" }) => RedirectingRequest;

/** Statuses whose response never has a body (`new Response` refuses one). */
const NO_BODY = new Set([101, 204, 205, 304]);

function toResponse(message: IncomingResponse): Response {
  const headers = new Headers();
  for (const [name, value] of Object.entries(message.headers)) {
    headers.set(name, Array.isArray(value) ? value.join(", ") : value);
  }
  const body = NO_BODY.has(message.statusCode)
    ? null
    : (Readable.toWeb(message) as ReadableStream<Uint8Array>);
  return new Response(body, {
    status: message.statusCode,
    statusText: message.statusMessage,
    headers,
  });
}

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return "an invalid URL";
  }
}

export function releaseRequest(open: OpenRequest): ReleaseRequest {
  return (url, { signal, allowRedirect }) =>
    new Promise<Response>((resolve, reject) => {
      if (signal.aborted) {
        reject(signal.reason as Error);
        return;
      }
      const request = open({ url, redirect: "manual" });
      let settled = false;
      const fail = (error: Error) => {
        if (settled) return;
        settled = true;
        reject(error);
      };
      const onAbort = () => {
        request.abort();
        fail(signal.reason as Error);
      };
      signal.addEventListener("abort", onAbort, { once: true });
      request.on("redirect", (_status: number, _method: string, location: string) => {
        if (allowRedirect(location)) {
          request.followRedirect();
          return;
        }
        request.abort();
        fail(new Error(`redirect refused: ${hostOf(location)}`));
      });
      request.on("response", (message: IncomingResponse) => {
        if (settled) return;
        settled = true;
        resolve(toResponse(message));
      });
      request.on("error", fail);
      request.end();
    });
}
