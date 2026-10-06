import httpx

from powereditor.settings_store import SettingsService
from powereditor.transcribe.base import Transcriber
from powereditor.transcribe.local_whisper import LocalWhisperTranscriber
from powereditor.transcribe.openai_whisper import OpenAIWhisperTranscriber


class TranscriberConfigError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def create_transcriber(
    service: SettingsService, *, transport: httpx.BaseTransport | None = None
) -> Transcriber:
    settings = service.get_effective()
    if settings.transcriber == "openai":
        api_key = service.get_secret("openai_api_key")
        if not api_key:
            raise TranscriberConfigError(
                "missing_openai_key", "Set an OpenAI API key in settings to use the openai provider"
            )
        ffmpeg = service.locate_executable("ffmpeg")
        if ffmpeg is None:
            raise TranscriberConfigError("missing_ffmpeg", "ffmpeg not found")
        return OpenAIWhisperTranscriber(api_key, ffmpeg, transport=transport)
    return LocalWhisperTranscriber(
        service.resolved_whisper_model(),
        settings.whisper_device,
        service.paths.models_dir,
        cuda_available=service.cuda_available(),
    )
