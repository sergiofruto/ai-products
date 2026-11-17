"""Shared data types."""
from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class Item:
    id: str  # sha1(url + "|" + topic)[:12]
    topic: str
    source: str
    kind: Literal["primary", "wire", "outlet"]
    url: str
    host: str
    title: str
    published: datetime  # UTC
    text: str
    lang: Literal["en", "es"]
    reliability: float
    wire: str | None = None
