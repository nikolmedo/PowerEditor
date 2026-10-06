"""Feature prompts as data: one typed question per AI feature, with its minimal state.

Rules (PLAN.md, "Rules for every model"): literal instructions, only the state the
question needs, no counting or arithmetic asked of the model. Bump a feature's `version`
whenever its wording changes; the version is part of the takes stage cache key.
"""

from dataclasses import dataclass
from string import ascii_uppercase

from powereditor.providers.config import FeatureId
from powereditor.providers.questions import ChoiceQuestion, NoulQuestion, Question, ScoreQuestion

SEGMENT_TEXT = "segment_text"
"""State key shared by every single-text question, so answers can be reused."""


@dataclass(frozen=True)
class FeaturePrompt:
    question_id: str
    question: Question
    version: int = 1


AUDIENCE_CONTENT = FeaturePrompt(
    "is_audience_content",
    NoulQuestion(
        instructions=(
            f"Is `{SEGMENT_TEXT}` part of the video's message to its audience? It was "
            "transcribed from a recording session of a talking-head video."
        ),
        when_true="The speaker is talking to the audience as part of the video.",
        when_false=(
            "An out-of-take remark to the crew or to themselves, such as asking to cut, "
            'to start again, or whether it is recording ("corta", "otra vez", "sorry, '
            'from the top").'
        ),
    ),
)

IDEA_COMPLETE = FeaturePrompt(
    "idea_complete",
    NoulQuestion(
        instructions=f"Does `{SEGMENT_TEXT}` end with its idea complete?",
        when_true="The last sentence finishes its thought.",
        when_false="The speech stops mid-sentence or before the idea is finished.",
    ),
)

CALL_TO_ACTION = FeaturePrompt(
    "has_call_to_action",
    NoulQuestion(
        instructions=f"Does `{SEGMENT_TEXT}` ask the audience to take an action?",
        when_true="It asks to subscribe, follow, like, comment, click a link or buy.",
        when_false="It contains no request for the audience to act.",
    ),
)

SAME_LINE = FeaturePrompt(
    "same_line",
    NoulQuestion(
        instructions=(
            "Are `first_text` and `second_text` two attempts at saying the same part of a "
            "script, where the speaker restarted the line?"
        ),
        when_true="Both say the same part, possibly with different wording or mistakes.",
        when_false="They are different parts of the script.",
    ),
)

FLUENCY = FeaturePrompt(
    "fluency",
    ScoreQuestion(
        instructions=f"How fluent and natural does `{SEGMENT_TEXT}` read as spoken delivery?",
        levels=[
            "Very hesitant: frequent fillers, restarts or broken sentences.",
            "Hesitant: several fillers or stumbles that distract.",
            "Acceptable: a few small hesitations.",
            "Fluent: smooth delivery with at most one small slip.",
            "Fully fluent and natural, with no hesitation.",
        ],
    ),
)

TOPIC_CHANGE = FeaturePrompt(
    "topic_change",
    NoulQuestion(
        instructions=(
            "Does the video move to a new topic between `previous_segment` and `next_segment`?"
        ),
        when_true="`next_segment` starts a new topic or section.",
        when_false="`next_segment` continues the same topic.",
    ),
)

BEST_TAKE_ID = "best_take"
BEST_TAKE_VERSION = 1
MAX_CHOICE_TAKES = len(ascii_uppercase)

SEGMENT_PROMPTS: dict[FeatureId, FeaturePrompt] = {
    "off_take_detection": AUDIENCE_CONTENT,
    "idea_completeness": IDEA_COMPLETE,
    "cta_detection": CALL_TO_ACTION,
}
TAKE_PROMPTS: dict[FeatureId, FeaturePrompt] = {
    "fluency_score": FLUENCY,
    "idea_completeness": IDEA_COMPLETE,
}
PROMPT_VERSIONS: dict[FeatureId, int] = {
    "off_take_detection": AUDIENCE_CONTENT.version,
    "idea_completeness": IDEA_COMPLETE.version,
    "cta_detection": CALL_TO_ACTION.version,
    "same_take_grey_zone": SAME_LINE.version,
    "fluency_score": FLUENCY.version,
    "topic_change": TOPIC_CHANGE.version,
    "best_take_choice": BEST_TAKE_VERSION,
}


def take_labels(count: int) -> list[str]:
    return list(ascii_uppercase[:count])


def best_take_question(labels: list[str]) -> ChoiceQuestion:
    """Options in the order given; the engine asks twice, the second time reversed."""
    return ChoiceQuestion(
        instructions=(
            "`takes` holds attempts at the same line of a talking-head video. Which take "
            "is the best one to keep: complete, fluent and natural, without restarts?"
        ),
        options={label: f"The take labelled {label} in `takes`." for label in labels},
    )
