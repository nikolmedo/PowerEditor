"""SRT and ASS files from the timeline subtitles, grouped into the same lines as the video."""

from typing import Literal

from powereditor.export.subtitles import SubtitleLine, group_lines
from powereditor.models import Project, ProjectPreset, SubtitlePosition, SubtitleStyle
from powereditor.timeline import timeline_layout

SubtitleFormat = Literal["srt", "ass"]
FONT_FAMILY = "Inter"
DIMENSIONS: dict[ProjectPreset, tuple[int, int]] = {
    "reel_9x16": (1080, 1920),
    "landscape_16x9": (1920, 1080),
}
# Safe-area margins (top, bottom, left, right) as fractions of the frame; mirrors
# `packages/composition/src/subtitles/styles.ts`.
SAFE_AREAS: dict[ProjectPreset, tuple[float, float, float, float]] = {
    "reel_9x16": (0.12, 0.24, 0.06, 0.16),
    "landscape_16x9": (0.08, 0.1, 0.06, 0.06),
}
_ALIGNMENT: dict[SubtitlePosition, int] = {"bottom": 2, "center": 5, "top": 8}


def _lines(project: Project) -> list[SubtitleLine]:
    return group_lines(
        project.subtitles.words,
        max_words_per_line=project.subtitles.style.max_words_per_line,
        fps=project.fps,
        duration_frames=timeline_layout(project).duration_in_frames,
    )


def _srt_time(frame: int, fps: int) -> str:
    total_ms = round(frame * 1000 / fps)
    seconds, ms = divmod(total_ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}"


def write_srt(project: Project) -> str:
    cues = [
        f"{index}\n{_srt_time(line.start_frame, project.fps)} --> "
        f"{_srt_time(line.end_frame, project.fps)}\n{line.text}\n"
        for index, line in enumerate(_lines(project), start=1)
    ]
    return "\n".join(cues)


def ass_color(hex_rgb: str) -> str:
    """`#RRGGBB` → ASS `&HAABBGGRR` (opaque)."""
    value = hex_rgb.lstrip("#")
    red, green, blue = value[0:2], value[2:4], value[4:6]
    return f"&H00{blue}{green}{red}".upper()


def _centiseconds(frame: int, fps: int) -> int:
    return round(frame * 100 / fps)


def _ass_time(centiseconds: int) -> str:
    seconds, cs = divmod(centiseconds, 100)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:d}:{minutes:02d}:{seconds:02d}.{cs:02d}"


def _ass_text(text: str) -> str:
    """Drop the characters that open override blocks or escapes."""
    return text.replace("{", "").replace("}", "").replace("\\", "")


def _karaoke(line: SubtitleLine, fps: int) -> str:
    """`{\\kN}word` per word; N runs to the next word's start, so gaps stay highlighted."""
    starts = [_centiseconds(word.start_frame, fps) for word in line.words]
    ends = [*starts[1:], _centiseconds(line.words[-1].end_frame, fps)]
    return " ".join(
        f"{{\\k{max(end - start, 0)}}}{_ass_text(word.text)}"
        for word, start, end in zip(line.words, starts, ends, strict=True)
    )


def _style_line(style: SubtitleStyle, preset: ProjectPreset) -> str:
    width, height = DIMENSIONS[preset]
    top, bottom, left, right = SAFE_AREAS[preset]
    margin_v = {"bottom": bottom * height, "top": top * height, "center": 0.0}[style.position]
    karaoke = style.preset == "karaoke_highlight"
    primary = ass_color(style.highlight_color) if karaoke else "&H00FFFFFF"
    bold = 0 if style.preset == "minimal" else -1
    border_style, outline = (3, 2) if style.preset == "minimal" else (1, 3)
    fields = [
        "Default", FONT_FAMILY, str(style.font_size), primary, "&H00FFFFFF", "&H00000000",
        "&H80000000", str(bold), "0", "0", "0", "100", "100", "0", "0", str(border_style),
        str(outline), "0", str(_ALIGNMENT[style.position]), str(round(left * width)),
        str(round(right * width)), str(round(margin_v)), "1",
    ]  # fmt: skip
    return "Style: " + ",".join(fields)


def write_ass(project: Project) -> str:
    style = project.subtitles.style
    width, height = DIMENSIONS[project.preset]
    karaoke = style.preset == "karaoke_highlight"
    events = []
    for line in _lines(project):
        start = _centiseconds(line.start_frame, project.fps)
        end = _centiseconds(line.end_frame, project.fps)
        text = _karaoke(line, project.fps) if karaoke else _ass_text(line.text)
        events.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{text}")
    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour,"
        " BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle,"
        " BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        _style_line(style, project.preset),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    return "\n".join([*header, *events]) + "\n"


def write_subtitles(project: Project, file_format: SubtitleFormat) -> str:
    return write_srt(project) if file_format == "srt" else write_ass(project)
