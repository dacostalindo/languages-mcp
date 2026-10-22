"""Pydantic models for content the agent writes and `render_styled` renders: explanations, exercise sets and
`find_exercises` result cards.

Every field is length-limited and treated as plain text. Text fields in `ExplanationSection.body`, `summary`,
`explanation` and `instructions` may use a tiny markdown subset (**bold**, *italic*, `code`, "- " bullets,
blank-line paragraphs), which styled.py turns into escaped HTML.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

GAP = "___"
"""Marks a gap in a gap-fill item: three or more underscores."""
GAP_RE = re.compile(r"_{3,}")

Short = Annotated[str, Field(min_length=1, max_length=200)]
Text = Annotated[str, Field(max_length=2000)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------------------------------------- explanation


class Example(_Model):
    nl: str = Field(min_length=1, max_length=300, description="Dutch sentence.")
    en: str = Field("", max_length=300, description="Translation (English or the learner's language).")
    note: str = Field("", max_length=300, description="Optional short note, e.g. which rule it shows.")


class ExplanationSection(_Model):
    heading: Short
    body: Text = Field(description="Plain text; supports **bold**, *italic*, `code` and '- ' bullet lines.")


class Table(_Model):
    caption: str = Field("", max_length=200)
    headers: list[Annotated[str, Field(max_length=200)]] = Field(
        min_length=1, max_length=8, description="Column headers; leave the first one empty to make the first "
        "column row headers (e.g. pronouns in a conjugation table).")
    rows: list[list[Annotated[str, Field(max_length=200)]]] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def _rectangular(self) -> Table:
        for i, row in enumerate(self.rows):
            if len(row) != len(self.headers):
                raise ValueError(f"table row {i} has {len(row)} cells but there are {len(self.headers)} headers")
        return self


class Mistake(_Model):
    wrong: Short = Field(description="The typical wrong form, e.g. 'Ik heb naar huis gegaan.'")
    right: Short = Field(description="The correct form, e.g. 'Ik ben naar huis gegaan.'")
    why: str = Field("", max_length=400, description="Short reason.")


class Explanation(_Model):
    title: Short
    level: str = Field("", max_length=20)
    summary: Text = ""
    sections: list[ExplanationSection] = Field(default_factory=list, max_length=12)
    examples: list[Example] = Field(default_factory=list, max_length=30)
    table: Table | None = None
    common_mistakes: list[Mistake] = Field(default_factory=list, max_length=15)


# ----------------------------------------------------------------------------------------------- exercises


class _Item(_Model):
    id: str = Field("", max_length=40, description="Optional item id; assigned automatically when empty.")
    explanation: str = Field("", max_length=600, description="Shown after checking: why the answer is right.")


class MultipleChoice(_Item):
    type: Literal["mc"]
    prompt: Short = Field(max_length=400)
    options: list[Short] = Field(min_length=2, max_length=6)
    answer: int = Field(ge=0, description="0-based index of the correct option.")

    @model_validator(mode="after")
    def _answer_in_range(self) -> MultipleChoice:
        if self.answer >= len(self.options):
            raise ValueError(f"answer index {self.answer} is out of range for {len(self.options)} options")
        if len({o.casefold() for o in self.options}) != len(self.options):
            raise ValueError("options must be distinct")
        return self


class GapFill(_Item):
    type: Literal["gap"]
    text: str = Field(min_length=1, max_length=600,
                      description="Sentence with each gap written as ___ , e.g. 'Ik ___ naar huis gegaan.'")
    answers: list[list[Short]] = Field(min_length=1, max_length=8,
                                       description="Accepted answers per gap, in order: [['ben']] or "
                                       "[['heb'], ['gemaakt']]. List alternatives for one gap together.")
    hint: str = Field("", max_length=200, description="Optional hint, e.g. the infinitive '(gaan)'.")

    @field_validator("answers", mode="before")
    @classmethod
    def _wrap_strings(cls, v):
        # Accept the natural shorthand ["ben", "gemaakt"] = one accepted answer per gap.
        if isinstance(v, list):
            return [[a] if isinstance(a, str) else a for a in v]
        return v

    @model_validator(mode="after")
    def _gaps_match_answers(self) -> GapFill:
        gaps = len(GAP_RE.findall(self.text))
        if gaps == 0:
            raise ValueError(f"gap text has no gaps; mark each gap with {GAP}")
        if gaps != len(self.answers):
            raise ValueError(f"gap text has {gaps} gap(s) but {len(self.answers)} answer list(s)")
        if any(not alts for alts in self.answers):
            raise ValueError("every gap needs at least one accepted answer")
        return self


class WordOrder(_Item):
    type: Literal["order"]
    prompt: str = Field("", max_length=300, description="Optional, e.g. the English sentence to build.")
    words: list[Annotated[str, Field(min_length=1, max_length=60)]] = Field(
        min_length=2, max_length=16, description="The words (or chunks) in the CORRECT order; the page shuffles them.")
    alternatives: list[list[Annotated[str, Field(min_length=1, max_length=60)]]] = Field(
        default_factory=list, max_length=5, description="Other correct orders of the same words.")

    @model_validator(mode="after")
    def _alternatives_use_same_words(self) -> WordOrder:
        key = sorted(w.casefold() for w in self.words)
        for alt in self.alternatives:
            if sorted(w.casefold() for w in alt) != key:
                raise ValueError("each alternative must use exactly the same words")
        return self


class Pair(_Model):
    left: Short
    right: Short


class Matching(_Item):
    type: Literal["match"]
    prompt: str = Field("", max_length=300)
    pairs: list[Pair] = Field(min_length=2, max_length=10)

    @model_validator(mode="after")
    def _distinct(self) -> Matching:
        for side in ("left", "right"):
            vals = [getattr(p, side).casefold() for p in self.pairs]
            if len(set(vals)) != len(vals):
                raise ValueError(f"matching pairs need distinct {side} values")
        return self


class TrueFalse(_Item):
    type: Literal["truefalse"]
    statement: Short = Field(max_length=400)
    answer: bool


Item = Annotated[MultipleChoice | GapFill | WordOrder | Matching | TrueFalse, Field(discriminator="type")]


class ExerciseSet(_Model):
    title: Short
    level: str = Field("", max_length=20)
    theme: str = Field("", max_length=120)
    instructions: Text = ""
    items: list[Item] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def _ids(self) -> ExerciseSet:
        seen: set[str] = set()
        for i, item in enumerate(self.items, 1):
            if not item.id:
                item.id = f"q{i}"
            if item.id in seen:
                raise ValueError(f"duplicate item id {item.id!r}")
            seen.add(item.id)
        return self


# ---------------------------------------------------------------------------------------------- exercise cards


class ExerciseCard(BaseModel):
    """One `find_exercises` result, as rendered on a results page. Extra keys are kept."""

    model_config = ConfigDict(extra="allow")

    title: str = Field(max_length=300)
    url: str = Field(max_length=2000)
    score: int | float = 0
    source: str = ""
    level: dict = Field(default_factory=dict)
    skills: list[str] = Field(default_factory=list)
    formats: list[str] = Field(default_factory=list)
    why: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @field_validator("url")
    @classmethod
    def _http(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("url must be http(s)")
        return v


# ------------------------------------------------------------------------------------------------- helpers


def answer_key(item) -> str:
    """Human-readable answer for one item (used in text fallbacks)."""
    if isinstance(item, MultipleChoice):
        return item.options[item.answer]
    if isinstance(item, GapFill):
        return " | ".join(" / ".join(alts) for alts in item.answers)
    if isinstance(item, WordOrder):
        return " ".join(item.words)
    if isinstance(item, Matching):
        return "; ".join(f"{p.left} = {p.right}" for p in item.pairs)
    if isinstance(item, TrueFalse):
        return "waar (true)" if item.answer else "niet waar (false)"
    raise TypeError(type(item))
