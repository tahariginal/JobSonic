"""Consistent online backup of the SQLite database + uploaded documents. Keeps the newest N."""
from __future__ import annotations

import sqlite3
import sys
import tarfile
from datetime import datetime, timezone

from .config import get_settings

KEEP = 14


def main() -> None:
    s = get_settings()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    db_path = s.data_dir / "sonic.db"
    if not db_path.is_file():
        sys.exit("database not found")
    tmp = s.backups_dir / f"sonic-{stamp}.db"
    src = sqlite3.connect(str(db_path))
    dst = sqlite3.connect(str(tmp))
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    out = s.backups_dir / f"sonic-{stamp}.tar.gz"
    with tarfile.open(out, "w:gz") as tar:
        tar.add(tmp, arcname="sonic.db")
        tar.add(s.uploads_dir, arcname="uploads")
    tmp.unlink()
    out.chmod(0o600)
    backups = sorted(s.backups_dir.glob("sonic-*.tar.gz"))
    for old in backups[:-KEEP]:
        old.unlink()
    print(f"backup written: {out.name} ({out.stat().st_size // 1024} KiB), {min(len(backups), KEEP)} kept")


if __name__ == "__main__":
    main()
