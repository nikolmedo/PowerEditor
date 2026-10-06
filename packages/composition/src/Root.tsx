import { Composition } from "remotion";

import fixture from "../test/fixtures/project.json";
import { COMPOSITION_ID } from "./compositionId";
import { videoMetadata } from "./metadata";
import { ProjectVideo, type ProjectVideoProps } from "./ProjectVideo";
import type { Project } from "./types";

const defaultProps: ProjectVideoProps = {
  project: fixture.project as Project,
  audioCrossfadeMs: 15,
  mediaBaseUrl: "http://127.0.0.1:0",
};

export const Root: React.FC = () => (
  <Composition
    id={COMPOSITION_ID}
    component={ProjectVideo}
    defaultProps={defaultProps}
    calculateMetadata={({ props }) => videoMetadata(props.project)}
    // Placeholders; calculateMetadata derives the real values from the project.
    durationInFrames={1}
    fps={30}
    width={1080}
    height={1920}
  />
);
