"""Self-check for merging DingTalk's encrypted WAL pages into a decrypted DB.

Run: python -m unittest test_decrypt -v
"""

import os
import shutil
import sqlite3
import struct
import tempfile
import unittest

from Crypto.Cipher import AES

import decrypt

_PAGE = 4096
_KEY = b"0123456789abcdef"


def _make_db(path):
    """Create a small DB with two rows."""
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA page_size={_PAGE}")
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, title TEXT)")
    conn.executemany("INSERT INTO t (title) VALUES (?)", [("a",), ("b",)])
    conn.commit()
    conn.close()


def _add_extra_row(path):
    """Add the row that will exist only in the WAL snapshot."""
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO t (title) VALUES ('wal-only')")
    conn.commit()
    conn.close()


def _build_encrypted_wal(wal_path, old_db, new_db):
    """Write a WAL holding every page that differs between the two DB snapshots."""
    with open(old_db, "rb") as f:
        old = f.read()
    with open(new_db, "rb") as f:
        new = f.read()

    changed = [i for i in range(len(new) // _PAGE) if old[i * _PAGE:(i + 1) * _PAGE] != new[i * _PAGE:(i + 1) * _PAGE]]
    cipher = AES.new(_KEY, AES.MODE_ECB)
    salt1, salt2 = 0x11111111, 0x22222222
    out = bytearray(struct.pack(">6I", 0x377F0682, 3007000, _PAGE, 0, salt1, salt2) + b"\0" * 8)
    for n, page_idx in enumerate(changed):
        commit = len(new) // _PAGE if n == len(changed) - 1 else 0
        page = new[page_idx * _PAGE:(page_idx + 1) * _PAGE]
        out += struct.pack(">4I", page_idx + 1, commit, salt1, salt2) + b"\0" * 8
        out += cipher.encrypt(page)
    with open(wal_path, "wb") as f:
        f.write(out)


class WalMergeTest(unittest.TestCase):
    """Committed WAL pages must be applied to a freshly decrypted database."""

    def test_applies_committed_frames(self):
        """A row written only to the WAL shows up after the merge."""
        with tempfile.TemporaryDirectory() as tmp:
            old_db = os.path.join(tmp, "old.db")
            new_db = os.path.join(tmp, "new.db")
            _make_db(old_db)
            shutil.copy(old_db, new_db)
            _add_extra_row(new_db)

            wal_path = old_db + "-wal"
            _build_encrypted_wal(wal_path, old_db, new_db)

            applied = decrypt._apply_wal_pages(old_db, wal_path, _KEY)
            self.assertGreater(applied, 0)

            conn = sqlite3.connect(old_db)
            titles = {r[0] for r in conn.execute("SELECT title FROM t")}
            conn.close()
            self.assertEqual(titles, {"a", "b", "wal-only"})


if __name__ == "__main__":
    unittest.main()
