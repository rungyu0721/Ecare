import os
import unittest

os.environ["ECARE_SKIP_INIT_DB"] = "1"

from backend.main import UserCreate, find_existing_user_id  # noqa: E402


class FakeCursor:
    def __init__(self, row):
        self.row = row
        self.calls = []

    def execute(self, query, params):
        self.calls.append((query, params))

    def fetchone(self):
        return self.row


class UserProfilePersistenceTests(unittest.TestCase):
    def test_find_existing_user_id_returns_latest_match(self):
        cursor = FakeCursor({"id": 6})
        payload = UserCreate(name="王小美", phone="0912345678")

        user_id = find_existing_user_id(cursor, payload)

        self.assertEqual(user_id, 6)
        self.assertEqual(len(cursor.calls), 1)
        self.assertEqual(cursor.calls[0][1], ("王小美", "0912345678"))

    def test_find_existing_user_id_skips_lookup_without_phone(self):
        cursor = FakeCursor({"id": 9})
        payload = UserCreate(name="王小美", phone=None)

        user_id = find_existing_user_id(cursor, payload)

        self.assertIsNone(user_id)
        self.assertEqual(cursor.calls, [])


if __name__ == "__main__":
    unittest.main()
