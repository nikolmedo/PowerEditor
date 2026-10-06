import { createContext } from "react";

import type { Source } from "../types";

/** Maps a source to the URL the composition should load for it. */
export type MediaResolver = (source: Source) => string;

/**
 * Overrides how sources are loaded. Renders leave it unset and stream mezzanines
 * from `mediaBaseUrl`; the editor's Player provides a resolver that serves proxies.
 */
export const MediaResolverContext = createContext<MediaResolver | null>(null);

/** URL of a project media file served flat (by file name) under `baseUrl`. */
export function mediaUrl(baseUrl: string, path: string): string {
  const fileName = path.split(/[\\/]/).pop() ?? path;
  return `${baseUrl.replace(/\/+$/, "")}/${encodeURIComponent(fileName)}`;
}

export function mezzanineResolver(baseUrl: string): MediaResolver {
  return (source) => mediaUrl(baseUrl, source.mezzaninePath);
}
