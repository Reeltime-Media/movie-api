from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Winner = Literal["red", "blue", "draw", "no_contest"]


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(value.split()) or None


class MatchDetailsWrite(BaseModel):
    """Fight card an admin enters for a Kun Khmer match."""

    red_fighter: str = Field(min_length=1, max_length=120)
    blue_fighter: str = Field(min_length=1, max_length=120)
    event_name: str | None = Field(default=None, max_length=160)
    weight_class: str | None = Field(default=None, max_length=60)
    match_date: date | None = None
    winner: Winner | None = None
    result_method: str | None = Field(default=None, max_length=60)
    result_round: int | None = Field(default=None, ge=1, le=20)

    @field_validator("red_fighter", "blue_fighter")
    @classmethod
    def fighter_required(cls, value: str) -> str:
        cleaned = _clean(value)
        if not cleaned:
            raise ValueError("Enter both fighters")
        return cleaned

    @field_validator("event_name", "weight_class", "result_method")
    @classmethod
    def blank_to_none(cls, value: str | None) -> str | None:
        return _clean(value)


class MatchDetailsRead(MatchDetailsWrite):
    model_config = {"from_attributes": True}
