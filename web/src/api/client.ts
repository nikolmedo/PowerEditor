import { isMessageKey, type Translate } from "../i18n";

export type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

/** A failed API call, normalized from the backend's three error shapes:
 * `{detail: {code, message}}`, `{detail: [{loc, msg}]}` (validation) and `{detail: "text"}`. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string | null,
    message: string,
    readonly fieldErrors: Record<string, string> = {},
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface ValidationIssue {
  loc?: unknown[];
  msg?: string;
}

function fieldOf(loc: unknown[] = []): string {
  return String(loc.filter((part) => part !== "body").join("."));
}

export function parseError(status: number, body: unknown): ApiError {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return new ApiError(status, null, detail);
  if (Array.isArray(detail)) {
    const fields = Object.fromEntries(
      (detail as ValidationIssue[]).map((issue) => [fieldOf(issue.loc), issue.msg ?? ""]),
    );
    return new ApiError(status, "validation", Object.values(fields).join("; "), fields);
  }
  if (detail && typeof detail === "object" && "message" in detail) {
    const { code, message } = detail as { code?: unknown; message?: unknown };
    return new ApiError(status, typeof code === "string" ? code : null, String(message));
  }
  return new ApiError(status, null, `HTTP ${status}`);
}

export async function request<T>(method: Method, path: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? null : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "network", "The local server is not reachable.");
  }
  const text = await response.text();
  const parsed: unknown = text ? JSON.parse(text) : undefined;
  if (!response.ok) throw parseError(response.status, parsed);
  return parsed as T;
}

/** A message for the user: a translated text for known codes, else the server's own words. */
export function errorMessage(error: unknown, t: Translate): string {
  if (!(error instanceof ApiError)) return t("error.unknown");
  const key = `error.${error.code ?? ""}`;
  if (error.code && isMessageKey(key)) return t(key);
  return error.message || t("error.unknown");
}
