from collections.abc import Sequence
from functools import partial
from pathlib import Path

from powereditor.models import Transcript
from powereditor.pipeline.ingest import IngestedSource, load_manifest
from powereditor.pipeline.runner import ProgressCallback, ProjectLayout, no_progress, run_stage
from powereditor.transcribe.base import Transcriber

TRANSCRIBE_STAGE_VERSION = 1


def transcribe_project(
    layout: ProjectLayout,
    transcriber: Transcriber,
    language: str | None,
    progress: ProgressCallback = no_progress,
    sources: Sequence[IngestedSource] | None = None,
) -> dict[str, Transcript]:
    """Transcribe ingested sources that have audio (default: all); cached per source."""
    transcripts: dict[str, Transcript] = {}
    for source in load_manifest(layout).sources if sources is None else sources:
        if source.wav_path is None:
            continue
        wav = Path(source.wav_path)
        params = {
            "provider": transcriber.provider,
            "model": transcriber.model,
            "language": language,
        }
        transcripts[source.source_id] = run_stage(
            layout,
            f"transcribe-{source.source_id}",
            TRANSCRIBE_STAGE_VERSION,
            [wav],
            params,
            Transcript,
            partial(transcriber.transcribe, wav, language),
            progress=progress,
        )
    return transcripts
