import type { AudioTrack, Project } from "@powereditor/composition";
import { useReducer, useRef, useState } from "react";
import { uploadFraction, uploadMusic, uploadReducer } from "../api/upload";
import {
  DUCKING_DB_RANGE,
  musicTrack,
  removeMusic,
  setDucking,
  setMusic,
  setNormalizeSources,
  setTrackVolume,
  TRACK_VOLUME_RANGE,
} from "../edit/audio";
import { useT } from "../i18n";
import { useProjectStore } from "../store/project";
import { ErrorNotice, Slider } from "../ui/primitives";
import { fileLabel } from "./timelineModel";

const MUSIC_TYPES = "audio/*,.mp3,.wav,.m4a,.aac,.ogg,.opus,.flac";
const percent = (volume: number) => `${Math.round(volume * 100)} %`;

function TrackVolume({ track }: { track: AudioTrack }) {
  const t = useT();
  const edit = useProjectStore((state) => state.edit);
  return (
    <Slider
      label={t("edit.volume")}
      value={track.volume}
      min={TRACK_VOLUME_RANGE[0]}
      max={TRACK_VOLUME_RANGE[1]}
      format={percent}
      onChange={(volume) =>
        edit((p) => setTrackVolume(p, track.id, volume), `track-volume:${track.id}`)
      }
    />
  );
}

function VoiceSection({ project }: { project: Project }) {
  const t = useT();
  const edit = useProjectStore((state) => state.edit);
  const voice = project.audioTracks.find((track) => track.kind === "voice");
  return (
    <section className="panel-body" aria-label={t("audio.voice")}>
      <h3>{t("audio.voice")}</h3>
      {voice && <TrackVolume track={voice} />}
      <label className="toggle">
        <input
          type="checkbox"
          checked={project.normalizeSources ?? false}
          onChange={(event) => edit((p) => setNormalizeSources(p, event.target.checked))}
        />
        {t("audio.normalize")}
      </label>
      <p className="meta">{t("audio.normalize.hint")}</p>
    </section>
  );
}

/** Pick a file, upload it to the project's media folder, then put it on the timeline. */
function MusicPicker({ projectId, replacing }: { projectId: string; replacing: boolean }) {
  const t = useT();
  const edit = useProjectStore((state) => state.edit);
  const picker = useRef<HTMLInputElement>(null);
  const [upload, dispatch] = useReducer(uploadReducer, { phase: "idle" });
  const [error, setError] = useState<unknown>(null);
  const label = replacing ? t("audio.replaceMusic") : t("audio.addMusic");

  const send = async (file: File) => {
    setError(null);
    dispatch({ type: "start", total: file.size });
    try {
      const sent = uploadMusic(projectId, file, (loaded, total) =>
        dispatch({ type: "progress", loaded, total }),
      );
      const stored = await sent.done;
      dispatch({ type: "done" });
      edit((p) => setMusic(p, stored.fileName));
    } catch (caught) {
      setError(caught);
      dispatch({ type: "done" });
    }
  };

  return (
    <>
      <button
        type="button"
        disabled={upload.phase === "uploading"}
        onClick={() => picker.current?.click()}
      >
        {label}
      </button>
      <input
        ref={picker}
        type="file"
        accept={MUSIC_TYPES}
        hidden
        aria-label={label}
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (file) void send(file);
        }}
      />
      {upload.phase === "uploading" && (
        <div className="row">
          <progress max={1} value={uploadFraction(upload)} aria-label={t("load.uploading")} />
          <span className="meta mono">
            {t("load.uploadProgress", { percent: Math.round(uploadFraction(upload) * 100) })}
          </span>
        </div>
      )}
      <ErrorNotice error={error} />
    </>
  );
}

function MusicSection({ projectId, project }: { projectId: string; project: Project }) {
  const t = useT();
  const edit = useProjectStore((state) => state.edit);
  const music = musicTrack(project);
  return (
    <section className="panel-body" aria-label={t("audio.music")}>
      <h3>{t("audio.music")}</h3>
      {music?.sourcePath ? (
        <>
          <p className="mono track-file">{fileLabel(music.sourcePath)}</p>
          <TrackVolume track={music} />
          <label className="toggle">
            <input
              type="checkbox"
              checked={music.duckingEnabled}
              onChange={(event) =>
                edit((p) => setDucking(p, music.id, { enabled: event.target.checked }))
              }
            />
            {t("audio.duck")}
          </label>
          <Slider
            label={t("audio.duckDepth")}
            value={music.duckingDb ?? 12}
            min={DUCKING_DB_RANGE[0]}
            max={DUCKING_DB_RANGE[1]}
            step={1}
            disabled={!music.duckingEnabled}
            format={(db) => `−${db} dB`}
            onChange={(db) => edit((p) => setDucking(p, music.id, { db }), `ducking:${music.id}`)}
          />
          <div className="row">
            <MusicPicker projectId={projectId} replacing />
            <button type="button" className="quiet" onClick={() => edit(removeMusic)}>
              {t("audio.removeMusic")}
            </button>
          </div>
        </>
      ) : (
        <>
          <p className="meta">{t("audio.noMusic")}</p>
          <MusicPicker projectId={projectId} replacing={false} />
        </>
      )}
      <p className="meta">{t("audio.previewNote")}</p>
    </section>
  );
}

/** Track levels: the voice (with source loudness matching) and an optional music bed. */
export function AudioPanel({ projectId, project }: { projectId: string; project: Project }) {
  return (
    <div className="panel-body">
      <VoiceSection project={project} />
      <MusicSection projectId={projectId} project={project} />
    </div>
  );
}
