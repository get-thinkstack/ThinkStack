"""crash-safe json persistence.

writing json by truncating a file in place means a crash, kill, or power
loss mid-write leaves a half-written (corrupt) file. ``atomic_write_json``
serializes to a sibling temp file, fsyncs it, then atomically renames it over
the target -- so a reader ever only sees the old complete file or the new
complete file, never a torn one. on any failure the original file is left
untouched and the temp file is removed.
"""

import json
import os
from pathlib import Path
from typing import Union


def atomic_write_json(path: Union[str, Path], data) -> None:
    """serialize ``data`` to ``path`` atomically.

    args:
        path: destination file path.
        data: any json-serializable object.

    raises:
        TypeError / ValueError: if ``data`` is not json-serializable. the
            existing file at ``path`` (if any) is preserved in this case.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")

    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        # atomic on the same filesystem: the target is replaced in one step,
        # so it is never observed partially written.
        os.replace(tmp, path)
    except BaseException:
        # serialization or io failed part-way -> discard the temp file and
        # leave whatever was already at ``path`` intact.
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise
