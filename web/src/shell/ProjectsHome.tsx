import { useCallback, useState } from "react";
import { api } from "../api/endpoints";
import type { ProjectListItem } from "../api/types";
import { useT } from "../i18n";
import { stepPath } from "../routes";
import { ErrorNotice, Status } from "../ui/primitives";
import { useResource } from "../ui/useResource";
import { Link } from "./AppShell";
import { projectStatus } from "./projectStatus";

function duration(seconds: number | null): string {
  if (seconds === null) return "--:--";
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

function ProjectCard({ project, onDeleted }: { project: ProjectListItem; onDeleted: () => void }) {
  const t = useT();
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const status = projectStatus(project);
  const open = stepPath(status === "ready" ? "review" : "load", project.id) as string;

  const remove = async () => {
    try {
      await api.deleteProject(project.id);
      onDeleted();
    } catch (caught) {
      setError(caught);
      setConfirming(false);
    }
  };

  return (
    <li className="project-card" aria-label={project.name}>
      <Link to={open} className="thumb">
        {project.thumbnailUrl && <video src={project.thumbnailUrl} muted preload="metadata" />}
        <span className="thumb-duration mono">{duration(project.durationSeconds)}</span>
      </Link>
      <div className="project-body">
        <p className="project-name">{project.name}</p>
        <p className="meta mono">{new Date(project.createdAt).toLocaleDateString()}</p>
        <Status ok={status === "ready" ? true : status === "error" ? false : null}>
          {t(`projects.status.${status}`)}
        </Status>
      </div>
      <div className="row">
        <Link to={open} className="button">
          {t("projects.open")}
        </Link>
        {confirming ? (
          <>
            <button type="button" className="danger" onClick={remove}>
              {t("projects.confirmDelete")}
            </button>
            <button type="button" className="quiet" onClick={() => setConfirming(false)}>
              {t("common.cancel")}
            </button>
          </>
        ) : (
          <button
            type="button"
            className="quiet danger"
            disabled={project.activeJobId !== null}
            onClick={() => setConfirming(true)}
          >
            {t("common.delete")}
          </button>
        )}
      </div>
      <ErrorNotice error={error} />
    </li>
  );
}

export function ProjectsHome() {
  const t = useT();
  const projects = useResource(useCallback(() => api.projects(), []));
  return (
    <section className="screen wide">
      <div className="screen-head">
        <h1>{t("projects.title")}</h1>
        <Link to="/load" className="button primary">
          {t("projects.new")}
        </Link>
      </div>
      <ErrorNotice error={projects.error} />
      {projects.data?.length === 0 && <p className="lede">{t("projects.empty")}</p>}
      <ul className="project-grid">
        {projects.data?.map((project) => (
          <ProjectCard
            key={project.id}
            project={project}
            onDeleted={() => void projects.reload()}
          />
        ))}
      </ul>
    </section>
  );
}
