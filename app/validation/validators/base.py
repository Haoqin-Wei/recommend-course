"""Validator abstract base."""

from __future__ import annotations
from abc import ABC, abstractmethod

from app.validation.types import ValidationContext, Issue


class Validator(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def check(self, ctx: ValidationContext) -> list[Issue]:
        ...
