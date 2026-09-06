"""Siril-compatible sequence file (.seq) helper."""

from pathlib import Path
from typing import List, Optional


def write_seq(path: Path, files: List[Path], prefix: str = "", digits: int = 4):
    """Write a Siril-compatible .seq file.
    
    Format:
        # format: seq
        # prefix: cal_
        # digits: 4
        0001 cal_0001.fit
        0002 cal_0002.fit
    """
    with open(path, "w", encoding="utf-8") as f:
        f.write("# format: seq\n")
        if prefix:
            f.write(f"# prefix: {prefix}\n")
        f.write(f"# digits: {digits}\n")
        for i, fp in enumerate(files):
            f.write(f"{i+1:0{digits}d} {fp.name}\n")


def read_seq(path: Path) -> List[Path]:
    """Read a Siril-compatible .seq file, returning list of file paths (relative to seq parent)."""
    files = []
    parent = path.parent
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                files.append(parent / parts[1])
    return files


def parse_seq_prefix(path: Path) -> Optional[str]:
    """Extract prefix from a .seq file header."""
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("# prefix:"):
                return line.split(":", 1)[1].strip()
    return None
