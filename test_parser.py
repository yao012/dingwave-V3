"""Self-check for message search / anchor pagination in parser.py.

Run: python -m unittest test_parser -v
"""

import json
import os
import tempfile
import unittest

import parser


def _build_db(path):
    """Create a minimal decrypted-DB look-alike with one conversation."""
    open(path, "a").close()  # get_connection() refuses to create the file itself
    conn = parser.get_connection(path)
    conn.execute(
        "CREATE TABLE tbconversation (cid TEXT, type INTEGER, title TEXT, memberCount INTEGER)"
    )
    conn.execute(
        "CREATE TABLE tbuser_profile_v2 (uid INTEGER, nick TEXT, realName TEXT, iconMediaId TEXT, mobile TEXT, email TEXT)"
    )
    conn.execute("CREATE TABLE im_image_info (cid TEXT, mid TEXT, url TEXT, local_path TEXT, size INTEGER)")
    conn.execute(
        '''CREATE TABLE "tbmsg_000" (primaryKey INTEGER, cid TEXT, localId INTEGER, mid TEXT,
           senderId INTEGER, type INTEGER, creatorType INTEGER, createdAt INTEGER,
           lastModify INTEGER, contentType INTEGER, content TEXT, recallStatus INTEGER,
           atIds TEXT, attachments TEXT, extension TEXT, readStatus INTEGER, sentlocaltime INTEGER)'''
    )
    conn.execute("INSERT INTO tbconversation VALUES ('g1', 2, '项目群', 8)")
    for i in range(120):
        conn.execute(
            'INSERT INTO "tbmsg_000" (mid, cid, senderId, type, createdAt, contentType, content, recallStatus, attachments) '
            "VALUES (?, 'g1', 1, 1, ?, 1, ?, 0, '')",
            (f"m{i}", 1000 + i,
             json.dumps({"text": f"消息 {i} 关键字" if i == 10 else f"消息 {i}"}, ensure_ascii=False)),
        )
    conn.commit()
    return conn


class ParserTest(unittest.TestCase):
    """Anchor pagination picks the page containing the hit; search carries group info."""

    def setUp(self):
        """Create a throwaway DB file for each test."""
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.conn = _build_db(os.path.join(self._tmp.name, "test.db"))
        self.addCleanup(self.conn.close)

    def test_anchor_newest_page(self):
        """Anchor in the newest page maps to reverse offset 0."""
        data = parser.get_messages(self.conn, "g1", limit=50, anchor_time=1100)
        ids = [m["id"] for m in data["messages"]]
        self.assertIn("m100", ids)
        self.assertEqual(data["offset"], 0)
        self.assertEqual(data["total"], 120)

    def test_anchor_oldest_page(self):
        """Anchor older than the last page still lands on the page containing it."""
        data = parser.get_messages(self.conn, "g1", limit=50, anchor_time=1000)
        ids = [m["id"] for m in data["messages"]]
        self.assertIn("m0", ids)
        self.assertEqual(len(ids), 50)

    def test_search_reports_conversation(self):
        """Search hits expose the group title and type for display/jumping."""
        results = parser.search_messages(self.conn, "关键字")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["conversation"]["title"], "项目群")
        self.assertEqual(results[0]["conversation"]["type"], "group")
        self.assertEqual(results[0]["conversation"]["member_count"], 8)


if __name__ == "__main__":
    unittest.main()
