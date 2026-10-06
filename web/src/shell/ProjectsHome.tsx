import { useCallback } from "react";
import { api } from "../api/endpoints";
import type { ProjectListItem } from "../api/types";
import { useT } from "../i18n";
import { ErrorNotice, Status } from "../ui/primitives";
import { useResource } from "../ui/useResource";
import { Link } from "./AppShell";

function duration(seconds: number | null): string {
  if (seconds === null) return "--:--";
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

function ProjectRow({ project }: { project: ProjectListItem }) {
  const t = useT();
  return (
    <li className="project">
      <div className="thumb">
        {project.thumbnailUrl && <video src={project.thumbnailUrl} muted preload="metadata" />}
      </div>
      <div>
        <p className="project-name">{project.name}</p>
        <p className="meta mono">
          {new Date(project.createdAt).toLocaleDateString()} · {duration(project.durationSeconds)}
        </p>
      </div>
      <Status ok={project.status === "analyzed" ? true : null}>
        {project.activeJobId ? t("projects.running") : t(`projects.status.${project.status}`)}
      </Status>
    </li>
  );
}

export function ProjectsHome() {
  const t = useT();
  const projects = useResource(useCallback(() => api.projects(), []));
  return (
    <section className="screen">
      <div className="screen-head">
        <h1>{t("projects.title")}</h1>
        <Link to="/load" className="button primary">
          {t("projects.new")}
        </Link>
      </div>
      <ErrorNotice error={projects.error} />
      {projects.data?.length === 0 && <p className="lede">{t("projects.empty")}</p>}
      <ul className="projects">
        {projects.data?.map((project) => (
          <ProjectRow key={project.id} project={project} />
        ))}
      </ul>
    </section>
  );
}
