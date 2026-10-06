from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any, Protocol

from powereditor.config import WhisperDevice
from powereditor.models import TranscriberProvider, Transcript
from powereditor.transcribe.base import RawWord, audio_duration, filler_prompt, normalize_words


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


class WhisperModelLike(Protocol):
    def transcribe(
        self, audio: str, **kwargs: Any
    ) -> tuple[Iterable[WhisperSegmentLike], WhisperInfoLike]: ...


ModelLoader = Callable[[str, str, str, Path], WhisperModelLike]


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
        loader: ModelLoader = load_faster_whisper,
    ) -> None:
        self._model_name = model_name
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
        segments, info = self._whisper().transcribe(
            str(audio_path),
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
            words=normalize_words(raw, audio_duration(audio_path)),
            provider="local",
            model=self._model_name,
        )
