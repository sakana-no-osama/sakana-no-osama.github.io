"""Stable project paths and replacement only after a complete file is written."""
from contextlib import contextmanager
from pathlib import Path
import os
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


@contextmanager
def atomic_text_writer(path: Path, encoding: str = "utf-8", newline=None):
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding=encoding, newline=newline,
                                         dir=path.parent, prefix=".writing-", delete=False) as handle:
            temporary = Path(handle.name)
            yield handle
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()  # Only the temporary file created by this call.


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    with atomic_text_writer(path, encoding=encoding, newline="") as handle:
        handle.write(text)
