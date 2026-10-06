"""Optional visual take features: face centering and sharpness from sampled frames."""

import importlib.util
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from powereditor.models import Take

logger = logging.getLogger(__name__)

VisualMeasure = tuple[float | None, float | None]
# Laplacian variance that counts as fully sharp on a 540p proxy frame.
SHARPNESS_FULL_SCALE = 300.0
SAMPLE_POINTS = (0.25, 0.5, 0.75)


class VisualFeatureExtractor(Protocol):
    @property
    def name(self) -> str: ...

    def measure(self, take: Take) -> VisualMeasure:
        """(face centering, sharpness), each in [0, 1] or None when unknown."""
        ...


class NullVisualExtractor:
    name = "none"

    def measure(self, take: Take) -> VisualMeasure:
        return (None, None)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


class OpenCvVisualExtractor:
    """Samples a few proxy frames per take; needs the optional `vision` extra."""

    name = "opencv"

    def __init__(self, videos: Mapping[str, Path]) -> None:
        import cv2

        self._cv2: Any = cv2
        self._videos = dict(videos)
        self._faces: Any = self._cv2.CascadeClassifier(
            str(Path(self._cv2.data.haarcascades) / "haarcascade_frontalface_default.xml")
        )

    def _frame(self, path: Path, second: float) -> Any:
        capture = self._cv2.VideoCapture(str(path))
        try:
            capture.set(self._cv2.CAP_PROP_POS_MSEC, second * 1000)
            ok, frame = capture.read()
            return self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2GRAY) if ok else None
        finally:
            capture.release()

    def _face_centering(self, gray: Any) -> float | None:
        faces = self._faces.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)
        if len(faces) == 0:
            return None
        x, y, width, height = max(faces, key=lambda face: face[2] * face[3])
        frame_height, frame_width = gray.shape
        dx = abs(x + width / 2 - frame_width / 2) / (frame_width / 2)
        dy = abs(y + height / 2 - frame_height / 2) / (frame_height / 2)
        return float(max(1.0 - max(dx, dy), 0.0))

    def measure(self, take: Take) -> VisualMeasure:
        video = self._videos.get(take.source_id)
        if video is None:
            return (None, None)
        sharpness: list[float] = []
        centering: list[float] = []
        for point in SAMPLE_POINTS:
            gray = self._frame(video, take.start + point * (take.end - take.start))
            if gray is None:
                continue
            variance = float(self._cv2.Laplacian(gray, self._cv2.CV_64F).var())
            sharpness.append(min(variance / SHARPNESS_FULL_SCALE, 1.0))
            face = self._face_centering(gray)
            if face is not None:
                centering.append(face)
        return (_mean(centering), _mean(sharpness))


def create_visual_extractor(videos: Mapping[str, Path]) -> VisualFeatureExtractor:
    """OpenCV when the `vision` extra is installed, otherwise no visual features."""
    if importlib.util.find_spec("cv2") is None:
        logger.info("opencv-python-headless is not installed; skipping visual take features")
        return NullVisualExtractor()
    return OpenCvVisualExtractor(videos)
