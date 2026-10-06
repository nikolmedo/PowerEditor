import importlib.util
from pathlib import Path

import numpy as np
import pytest

from powereditor.decide.factory import create_engine
from powereditor.models import Take
from powereditor.pipeline import visual
from powereditor.pipeline.clustering import TextSimilarity, create_similarity
from powereditor.pipeline.visual import NullVisualExtractor, create_visual_extractor
from powereditor.settings_store import TakeWeights, UserSettings


def test_text_similarity_is_the_default() -> None:
    assert isinstance(create_similarity("text", "es"), TextSimilarity)


def test_embeddings_fall_back_to_text_when_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)

    assert isinstance(create_similarity("embeddings", "es"), TextSimilarity)


def test_visual_features_are_skipped_without_opencv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)

    extractor = create_visual_extractor({})

    assert isinstance(extractor, NullVisualExtractor)
    assert extractor.measure(
        Take(id="t", segment_id="s", source_id="a", start=0, end=1, text="")
    ) == (
        None,
        None,
    )


def test_engine_factory_falls_back_to_heuristic_with_user_weights() -> None:
    settings = UserSettings(decision_engine="jev", take_weights=TakeWeights(last_take=0.0))

    engine = create_engine(settings)

    assert engine.name == "heuristic"
    assert engine.fingerprint()["weights"]["lastTake"] == 0.0


def _write_video(path: Path, frame: np.ndarray) -> None:
    cv2 = pytest.importorskip("cv2")
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (160, 120))
    for _ in range(20):
        writer.write(cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR))
    writer.release()


def test_opencv_extractor_rates_detail_sharper_than_flat_frames(tmp_path: Path) -> None:
    pytest.importorskip("cv2")
    checker = (np.indices((120, 160)).sum(axis=0) // 8 % 2 * 255).astype(np.uint8)
    flat = np.full((120, 160), 128, dtype=np.uint8)
    _write_video(tmp_path / "checker.avi", checker)
    _write_video(tmp_path / "flat.avi", flat)
    extractor = visual.OpenCvVisualExtractor(
        {"checker": tmp_path / "checker.avi", "flat": tmp_path / "flat.avi"}
    )

    def take(source_id: str) -> Take:
        return Take(
            id=source_id, segment_id=source_id, source_id=source_id, start=0, end=1.5, text=""
        )

    sharp_face, sharp = extractor.measure(take("checker"))
    flat_face, blurry = extractor.measure(take("flat"))

    assert (sharp_face, flat_face) == (None, None)
    assert sharp is not None and blurry is not None
    assert sharp > 0.9
    assert blurry < 0.05


@pytest.mark.slow
def test_embedding_similarity_scores_paraphrases_above_unrelated_lines() -> None:
    pytest.importorskip("sentence_transformers")
    similarity = create_similarity("embeddings", "es")

    paraphrase = similarity("Hoy hablamos del café.", "Hoy vamos a hablar sobre el café.")
    unrelated = similarity("Hoy hablamos del café.", "El tren sale a las nueve.")

    assert paraphrase > unrelated
