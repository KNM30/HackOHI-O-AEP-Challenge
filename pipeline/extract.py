"""Extract the challenge archives without overwriting anything.

Mirrors the instructions in challenge_repo/data/README.md but works on Windows
without `unzip`. Each archive is extracted into its own folder so shapefile
companion files (.shp/.shx/.dbf/.prj/...) stay together.
"""
from __future__ import annotations

import zipfile

from common import EXTRACTED, RAW_DIR

ARCHIVES = {"Data1": "Data1.zip", "Data2": "Data2.zip", "matched_upstream": "matched_upstream.zip"}


def main() -> None:
    for folder, archive in ARCHIVES.items():
        src = RAW_DIR / "raw" / archive
        dest = EXTRACTED / folder
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(src) as zf:
            added = 0
            for member in zf.infolist():
                target = (dest / member.filename).resolve()
                if not str(target).startswith(str(dest.resolve())):
                    raise RuntimeError(f"unsafe path in {archive}: {member.filename}")
                if target.exists():
                    continue
                zf.extract(member, dest)
                added += 1
        print(f"{archive}: {added} new files -> {dest}")


if __name__ == "__main__":
    main()
