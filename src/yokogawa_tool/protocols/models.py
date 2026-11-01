"""Common decoded annotation model."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Annotation:
    start: float
    end: float
    kind: str
    text: str


