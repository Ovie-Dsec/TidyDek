from pathlib import Path
from typing import List, Dict, Optional
import fnmatch

class FileInfo:
    def __init__(self, path: Path):
        self.path = path
        self.size = path.stat().st_size if path.exists() else 0
        self.name = path.name
        self.extension = path.suffix

    def as_dict(self):
        return {
            "path": str(self.path),
            "size": self.size,
            "name": self.name,
            "extension": self.extension,
        }

class DirectoryScanner:
    def __init__(self, root: Path, include_patterns: Optional[List[str]] = None, exclude_patterns: Optional[List[str]] = None):
        self.root = root
        self.include_patterns = include_patterns or ["*"]
        self.exclude_patterns = exclude_patterns or []

    def scan(self) -> List[FileInfo]:
        files = []
        for path in self.root.rglob("*"):
            if path.is_file() and self._include(path.name) and not self._exclude(path.name):
                files.append(FileInfo(path))
        return files

    def _include(self, filename: str) -> bool:
        return any(fnmatch.fnmatch(filename, pat) for pat in self.include_patterns)

    def _exclude(self, filename: str) -> bool:
        return any(fnmatch.fnmatch(filename, pat) for pat in self.exclude_patterns)

class FileParser:
    def __init__(self, extensions: Optional[List[str]] = None):
        self.extensions = extensions or [".txt"]

    def parse(self, fileinfo: FileInfo) -> Dict:
        if fileinfo.extension not in self.extensions:
            raise ValueError(f"Unsupported file extension: {fileinfo.extension}")
        with open(fileinfo.path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"file": fileinfo.as_dict(), "content": content}
