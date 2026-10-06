import tempfile
import wave
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray

from powereditor.config import WhisperDevice
from powereditor.models import TranscriberProvider, Transcript
from powereditor.pipeline.ffmpeg import run_ffmpeg
from powereditor.pipeline.vad import read_wav
from powereditor.transcribe.base import (
    RawWord,
    TranscriptionError,
    filler_prompt,
    normalize_words,
)


class WhisperWordLike(Protocol):
    @property
    def word(self) -> str: ...

    @property
    def start(self) -> float: ...

    @property
    def end(self) -> float: ...

    @property
    def probability(self) -> float: ...


class WhisperSegmentLike(Protocol):
    @property
    def words(self) -> Sequence[WhisperWordLike] | None: ...


class WhisperInfoLike(Protocol):
    @property
    def language(self) -> str: ...


WhisperAudio = NDArray[np.float32]


class WhisperModelLike(Protocol):
    def transcribe(
        self, audio: WhisperAudio, **kwargs: Any
    ) -> tuple[Iterable[WhisperSegmentLike], WhisperInfoLike]: ...


def _is_whisper_wav(path: Path) -> bool:
    try:
        with wave.open(str(path), "rb") as handle:
            return handle.getframerate() == WHISPER_SAMPLE_RATE and handle.getsampwidth() == 2
    except (wave.Error, EOFError, OSError):
        return False


def whisper_audio(path: Path, ffmpeg: str | None) -> WhisperAudio:
    """Samples for faster-whisper, decoded here and never by faster-whisper itself.

    faster-whisper decodes paths with PyAV, which the frozen build leaves out (its wheel
    carries GPL x264/x265 libraries). A 16 kHz PCM WAV (what ingest writes) is read
    directly; anything else is converted to one with ffmpeg first.
    """
    if _is_whisper_wav(path):
        samples, _ = read_wav(path)
        return samples.astype(np.float32)
    if ffmpeg is None:
        raise TranscriptionError("missing_ffmpeg", f"ffmpeg is needed to read {path.name}")
    with tempfile.TemporaryDirectory(prefix="powereditor-whisper-") as folder:
        wav = Path(folder) / "audio.wav"
        run_ffmpeg(
            ffmpeg,
            [
                "-i", str(path), "-map", "0:a:0", "-vn",
                "-ac", "1", "-ar", str(WHISPER_SAMPLE_RATE), "-c:a", "pcm_s16le", str(wav),
            ],
        )  # fmt: skip
        samples, _ = read_wav(wav)
    return samples.astype(np.float32)


ModelLoader = Callable[[str, str, str, Path], WhisperModelLike]


WHISPER_SAMPLE_RATE = 16000


def load_faster_whisper(
    name: str, device: str, compute_type: str, download_root: Path
) -> WhisperModelLike:
    from faster_whisper import WhisperModel

    model: WhisperModelLike = WhisperModel(
        name, device=device, compute_type=compute_type, download_root=str(download_root)
    )
    return model


def ensure_model(name: str, models_dir: Path) -> Path:
    """Download a Whisper model into the app models dir (no-op if already cached).

    Progress is reported by huggingface_hub's own tqdm bars on stderr; callers that
    need structured progress should poll the size of `models_dir` while this runs.
    """
    from faster_whisper import download_model

    models_dir.mkdir(parents=True, exist_ok=True)
    return Path(download_model(name, cache_dir=str(models_dir)))


def is_model_cached(name: str, models_dir: Path) -> bool:
    """Whether `ensure_model` would find the model locally, without touching the network."""
    from faster_whisper import download_model

    try:
        download_model(name, cache_dir=str(models_dir), local_files_only=True)
    except Exception:  # huggingface_hub raises several error types for a missing model
        return False
    return True


def resolve_device(device: WhisperDevice, cuda_available: bool) -> tuple[str, str]:
    use_cuda = device == "cuda" or (device == "auto" and cuda_available)
    return ("cuda", "float16") if use_cuda else ("cpu", "int8")


class LocalWhisperTranscriber:
    def __init__(
        self,
        model_name: str,
        device: WhisperDevice,
        models_dir: Path,
        *,
        cuda_available: bool,
        ffmpeg: str | None = None,
        loader: ModelLoader = load_faster_whisper,
    ) -> None:
        self._model_name = model_name
        self._ffmpeg = ffmpeg
        self._device, self._compute_type = resolve_device(device, cuda_available)
        self._models_dir = models_dir
        self._loader = loader
        self._loaded: WhisperModelLike | None = None

    @property
    def provider(self) -> TranscriberProvider:
        return "local"

    @property
    def model(self) -> str:
        return self._model_name

    def _whisper(self) -> WhisperModelLike:
        if self._loaded is None:
            self._loaded = self._loader(
                self._model_name, self._device, self._compute_type, self._models_dir
            )
        return self._loaded

    def transcribe(self, audio_path: Path, language: str | None) -> Transcript:
        samples = whisper_audio(audio_path, self._ffmpeg)
        segments, info = self._whisper().transcribe(
            samples,
            language=language,
            initial_prompt=filler_prompt(language),
            word_timestamps=True,
            vad_filter=False,
        )
        raw = [
            RawWord(word.word, word.start, word.end, word.probability)
            for segment in segments
            for word in segment.words or ()
        ]
        return Transcript(
            language=language or info.language,
            words=normalize_words(raw, len(samples) / WHISPER_SAMPLE_RATE),
            provider="local",
            model=self._model_name,
        )
