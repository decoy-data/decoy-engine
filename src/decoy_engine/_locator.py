"""Stub: the recognizer lands in the next commit."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class LocatorKind(str, Enum):
    LOCAL = "local"
    DRIVE = "drive"
    DEVICE = "device"
    NETWORK = "network"
    URL = "url"


@dataclass(frozen=True, slots=True)
class LocatorScan:
    kind: LocatorKind
    shown: str
    carries_credentials: bool
    published: str | None


def scan_locator(text: str) -> LocatorScan:
    return LocatorScan(LocatorKind.LOCAL, text, False, text)
