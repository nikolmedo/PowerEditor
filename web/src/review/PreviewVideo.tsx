import {
  MediaResolverContext,
  mediaUrl,
  ProjectVideo,
  type MediaResolver,
  type ProjectVideoProps,
} from "@powereditor/composition";
import { useMemo } from "react";

/** Media of a project as the local API serves it. */
export function projectMediaBase(projectId: string): string {
  return `/api/projects/${encodeURIComponent(projectId)}/media`;
}

/** The render composition, fed with the light preview proxies instead of the mezzanines. */
export function PreviewVideo(props: ProjectVideoProps) {
  const { mediaBaseUrl } = props;
  const resolve = useMemo<MediaResolver>(
    () => (source) => mediaUrl(mediaBaseUrl, source.proxyPath),
    [mediaBaseUrl],
  );
  return (
    <MediaResolverContext.Provider value={resolve}>
      <ProjectVideo {...props} />
    </MediaResolverContext.Provider>
  );
}
