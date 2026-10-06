"""SRT and ASS export of the timeline subtitles, and the export-subtitles command."""

from typer.testing import CliRunner

from powereditor import cli
from powereditor.export.subtitle_files import ass_color, write_ass, write_srt
from powereditor.export.subtitles import rebuild_subtitles
from powereditor.models import Project, save_project
from powereditor.paths import AppPaths
from powereditor.pipeline.runner import ProjectLayout
from tests.test_subtitles import _project


def _styled(project: Project, **style: object) -> Project:
    updated = project.subtitles.style.model_copy(update=style)
    return project.model_copy(
        update={"subtitles": project.subtitles.model_copy(update={"style": updated})}
    )


def test_srt_has_one_cue_per_line_in_milliseconds() -> None:
    srt = write_srt(rebuild_subtitles(_project()))

    assert srt.startswith(
        "1\n00:00:00,100 --> 00:00:01,133\nHola a todos.\n\n"
        "2\n00:00:01,133 --> 00:00:01,800\nAhora Esto va\n\n"
    )
    assert srt.endswith("4\n00:00:03,300 --> 00:00:03,800\naquí\n")


def test_ass_karaoke_tags_follow_word_starts_in_centiseconds() -> None:
    ass = write_ass(rebuild_subtitles(_project()))

    dialogues = [line for line in ass.splitlines() if line.startswith("Dialogue:")]
    assert dialogues[0] == (
        r"Dialogue: 0,0:00:00.10,0:00:01.13,Default,,0,0,0,,{\k37}Hola {\k13}a {\k53}todos."
    )
    assert len(dialogues) == 4
    assert "PlayResX: 1080\nPlayResY: 1920" in ass
    # Karaoke: the highlight is the sung (primary) colour, white the colour before it.
    assert "Style: Default,Inter,64,&H0000D4FF,&H00FFFFFF," in ass


def test_ass_without_karaoke_uses_plain_text_and_the_preset_position() -> None:
    ass = write_ass(_styled(rebuild_subtitles(_project()), preset="clean", position="top"))

    style = next(line for line in ass.splitlines() if line.startswith("Style:"))
    dialogue = next(line for line in ass.splitlines() if line.startswith("Dialogue:"))
    assert dialogue.endswith(",,Hola a todos.")
    assert style.split(",")[18:22] == ["8", "65", "173", "230"]


def test_ass_text_cannot_inject_override_tags() -> None:
    project = rebuild_subtitles(_project())
    words = [w.model_copy(update={"text": r"{\b1}x"}) for w in project.subtitles.words]
    project = project.model_copy(
        update={"subtitles": project.subtitles.model_copy(update={"words": words})}
    )
    style_off = _styled(project, preset="minimal")

    assert r"{\b1}" not in write_ass(style_off)


def test_ass_color_converts_hex_rgb_to_bgr() -> None:
    assert ass_color("#FFD400") == "&H0000D4FF"
    assert ass_color("#0a0B0c") == "&H000C0B0A"


def test_export_subtitles_command_writes_the_file() -> None:
    layout = ProjectLayout.for_project(AppPaths.from_env(), "demo")
    layout.ensure()
    save_project(_project(), layout.project_file)

    result = CliRunner().invoke(cli.app, ["export-subtitles", "demo", "--format", "ass"])

    output = layout.root / "exports" / "subtitles.ass"
    assert result.exit_code == 0, result.output
    assert output.is_file()
    assert r"{\k37}Hola" in output.read_text(encoding="utf-8")


def test_export_subtitles_command_reports_a_missing_project() -> None:
    result = CliRunner().invoke(cli.app, ["export-subtitles", "nope"])

    assert result.exit_code == 1
    assert "project_not_found:" in result.output
