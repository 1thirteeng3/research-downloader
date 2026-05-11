"""
Result dataclass for standardizing fetcher return values.
Every fetcher returns a Result with: success, paths, error, source, metadata
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

@dataclass
class FetchResult:
    success: bool
    paths: List[str] = field(default_factory=list)
    error: str = ""
    source: str = ""           # "arxiv", "annas_archive", "web_search"
    items_found: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return not self.success

    @property
    def count(self) -> int:
        return len(self.paths)
