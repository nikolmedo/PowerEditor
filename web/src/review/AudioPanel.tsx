import type { AudioTrack, Clip, Project } from "@powereditor/composition";
import { useCallback, useEffect, useRef } from "react";
import type { MusicFile } from "../api/types";
import { uploadFraction, uploadMusic } from "../api/upload";
import {
  DUCKING_DB_RANGE,
  musicTrack,
  removeMusic,
  setDucking,
  setMusic,
  setNormalizeSources,
  setTrackMuted,
  setTrackVolume,
  TRACK_VOLUME_RANGE,
} from "../edit/audio";
import { useT } from "../i18n";
import { useProjectStore } from "../store/project";
import { ErrorNotice, Slider } from "../ui/primitives";
import { ClipVolume } from "./ClipPanel";
import { fileLabel } from "./timelineModel";
import { useLatestUpload } from "./useLatestUpload";

const MUSIC_TYPES = "audio/*,.mp3,.wav,.m4a,.aac,.ogg,.opus,.flac";
const percent = (volume: number) => `${Math.round(volume * 100)} %`;

/** The track the timeline selected: its section is highlighted and scrolled into view. */
export type FocusTrack = "voice" | "music";

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

function TrackMute({ track }: { track: AudioTrack }) {
  const t = useT();
  const edit = useProjectStore((state) => state.edit);
  return (
    <label className="toggle">
      <input
        type="checkbox"
        checked={track.muted ?? false}
        onChange={(event) => edit((p) => setTrackMuted(p, track.id, event.target.checked))}
      />
      {t("audio.mute")}
    </label>
  );
}

/** A section the timeline can focus: marked and scrolled into view when it gains the focus. */
function useFocusedSection(focused: boolean) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    // jsdom has no scrollIntoView.
    if (focused) ref.current?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, [focused]);
  return { ref, "data-focused": focused || undefined };
}

function VoiceSection({
  project,
  focused,
  clip,
}: {
  project: Project;
  focused: boolean;
  clip: Clip | null;
}) {
  const t = useT();
  const edit = useProjectStore((state) => state.edit);
  const section = useFocusedSection(focused);
  const voice = project.audioTracks.find((track) => track.kind === "voice");
  return (
    <section className="panel-body audio-section" aria-label={t("audio.voice")} {...section}>
      <h3>{t("audio.voice")}</h3>
      {voice && (
        <>
          <TrackVolume track={voice} />
          <TrackMute track={voice} />
        </>
      )}
      {focused && clip && <ClipVolume clip={clip} label={t("audio.clipLevel")} />}
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

/** Pick a file, upload it to the project's media folder, then put it on the timeline. Picking
 * another file while one uploads replaces it: only the newest upload reaches the project. */
function MusicPicker({ projectId, replacing }: { projectId: string; replacing: boolean }) {
  const t = useT();
  const edit = useProjectStore((state) => state.edit);
  const picker = useRef<HTMLInputElement>(null);
  const onStored = useCallback(
    (stored: MusicFile) => edit((p) => setMusic(p, stored.fileName)),
    [edit],
  );
  const { state: upload, error, send } = useLatestUpload(projectId, uploadMusic, onStored);
  const label = replacing ? t("audio.replaceMusic") : t("audio.addMusic");

  return (
    <>
      <button type="button" onClick={() => picker.current?.click()}>
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

function MusicSection({
  projectId,
  project,
  focused,
}: {
  projectId: string;
  project: Project;
  focused: boolean;
}) {
  const t = useT();
  const edit = useProjectStore((state) => state.edit);
  const section = useFocusedSection(focused);
  const music = musicTrack(project);
  return (
    <section className="panel-body audio-section" aria-label={t("audio.music")} {...section}>
      <h3>{t("audio.music")}</h3>
      {music?.sourcePath ? (
        <>
          <p className="mono track-file">{fileLabel(music.sourcePath)}</p>
          <TrackVolume track={music} />
          <TrackMute track={music} />
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

/** Track levels and mutes: the voice (with source loudness matching, and the selected clip's
 * level when the timeline focused the voice) and an optional music bed. */
export function AudioPanel({
  projectId,
  project,
  focusTrack = null,
  clip = null,
}: {
  projectId: string;
  project: Project;
  focusTrack?: FocusTrack | null;
  clip?: Clip | null;
}) {
  return (
    <div className="panel-body">
      <VoiceSection project={project} focused={focusTrack === "voice"} clip={clip} />
      <MusicSection projectId={projectId} project={project} focused={focusTrack === "music"} />
    </div>
  );
}
