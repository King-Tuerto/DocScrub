"""Mapper stub — implemented in Piece 7."""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class MappingEntry:
    original: str
    placeholder: str
    pii_type: str
    source: Optional[str] = None


@dataclass
class MappingTable:
    entries: List[MappingEntry] = field(default_factory=list)

    def get_placeholder(self, original: str) -> Optional[str]:
        for e in self.entries:
            if e.original == original:
                return e.placeholder
        return None


def build_mapping(findings) -> MappingTable:
    raise NotImplementedError("Piece 7 not yet built")
