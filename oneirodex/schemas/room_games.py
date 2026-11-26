"""Bounded original-room-game progress; independent of application/DB startup."""
from __future__ import annotations

from math import pi
import json
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator

_CONTENT = json.loads((Path(__file__).resolve().parents[1] / 'data' / 'room_games' / 'moonfall-v1.json').read_text(encoding='utf-8'))
MISSION_LENGTHS = tuple(len(mission['route']) for mission in _CONTENT['missions'])
IMPLEMENTED_ROOM_GAMES = frozenset({'moonfall-pinball'})
MAX_PROGRESS_BODY = 64 * 1024
Counter = Annotated[int, Field(ge=0, le=2_000_000_000)]
# A write stores revision + 1, so the highest revision a client may send is one
# below the ceiling. Bounding it here answers 422, not a misleading 409.
Revision = Annotated[int, Field(ge=0, lt=2_000_000_000)]


class _StrictSave(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)


class MoonfallBall(_StrictSave):
    id: int = Field(ge=1, le=1_000_000)
    x: float = Field(ge=-1.2, le=1.2)
    y: float = Field(ge=-0.2, le=4.2)
    vx: float = Field(ge=-50, le=50)
    vy: float = Field(ge=-50, le=50)
    cooldown: int = Field(ge=0, le=600)
    captureTicks: int = Field(ge=0, le=120)


class MoonfallFlippers(_StrictSave):
    left: float = Field(ge=-0.73, le=0.25)
    right: float = Field(ge=pi - 0.25, le=pi + 0.73)


class MoonfallSettings(_StrictSave):
    quality: Literal['low', 'standard', 'high']
    reducedMotion: bool
    muted: bool
    volume: float = Field(ge=0, le=1)
    highContrast: bool


class MoonfallFeatures(_StrictSave):
    ramps: int = Field(ge=0, le=1_000_000)
    returns: int = Field(ge=0, le=1_000_000)
    skillShots: int = Field(ge=0, le=1_000_000)
    rampTicks: int = Field(ge=0, le=180)
    rampSide: Literal[-1, 1]
    skillTicks: int = Field(ge=0, le=360)
    returnTicks: int = Field(ge=0, le=120)
    launchAim: float = Field(ge=-3.3, le=0)

    @field_validator('rampSide', mode='before')
    @classmethod
    def strict_side(cls, value):
        if type(value) is not int or value not in (-1, 1):
            raise ValueError('Unsupported or invalid Moonfall save')
        return value


class MoonfallSave(_StrictSave):
    version: int = Field(ge=1, le=1)
    seed: int = Field(ge=0, le=0xffffffff)
    phase: Literal['ready', 'playing', 'game-over', 'complete']
    tick: int = Field(ge=0, le=10_000_000)
    score: Counter
    best: Counter
    ballsRemaining: int = Field(ge=0, le=4)
    balls: list[MoonfallBall] = Field(max_length=3)
    nextBallId: int = Field(ge=1, le=1_000_000)
    missionHits: list[Annotated[int, Field(ge=0, le=max(MISSION_LENGTHS))]] = Field(min_length=3, max_length=3)
    combo: int = Field(ge=0, le=20)
    comboTicks: int = Field(ge=0, le=600)
    extraBallAwarded: bool
    recoveries: int = Field(ge=0, le=2)
    lastLaunch: bool
    lastRecover: bool
    settings: MoonfallSettings
    flippers: MoonfallFlippers
    features: MoonfallFeatures

    @model_validator(mode='after')
    def coherent_run(self) -> Self:
        invalid = (
            self.best < self.score
            or len({b.id for b in self.balls}) != len(self.balls)
            or any(b.id >= self.nextBallId for b in self.balls)
            or any(hit > limit for hit, limit in zip(self.missionHits, MISSION_LENGTHS))
            or any(self.missionHits[i] > 0 and self.missionHits[i - 1] != MISSION_LENGTHS[i - 1]
                   for i in (1, 2))
            or (self.phase == 'playing' and (not self.balls or self.ballsRemaining == 0))
            or (self.phase == 'ready' and (self.balls or self.ballsRemaining == 0))
            or (self.phase == 'complete' and tuple(self.missionHits) != MISSION_LENGTHS)
            or (self.phase == 'game-over' and self.ballsRemaining != 0 and self.tick < 10_000_000)
            or any(hit == limit and any(getattr(self.features,key) < needed for key,needed in mission['required'].items())
                   for hit,limit,mission in zip(self.missionHits,MISSION_LENGTHS,_CONTENT['missions']))
        )
        if invalid:
            raise ValueError('Unsupported or invalid Moonfall save')
        return self


class RoomGameSaveBody(_StrictSave):
    revision: Revision
    state: MoonfallSave


class RoomGameDeleteBody(_StrictSave):
    revision: Revision
