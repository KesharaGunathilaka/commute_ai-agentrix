"""Shared enumerations — imported by both domain models and graph state."""

from enum import StrEnum


class Language(StrEnum):
    SINHALA = "si"
    TAMIL = "ta"
    ENGLISH = "en"


class DisruptionType(StrEnum):
    DELAY = "delay"
    CANCELLATION = "cancellation"


class DisruptionLevel(StrEnum):
    CLEAR = "clear"
    DELAYED = "delayed"
    CANCELLED = "cancelled"


class TrainType(StrEnum):
    INTERCITY_EXPRESS = "InterCity Express"
    INTERCITY = "Intercity"
    SLOW = "Slow"


class TransitMode(StrEnum):
    TRAIN = "train"
    BUS = "bus"
