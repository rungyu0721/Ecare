import unittest
import os

os.environ["ECARE_SKIP_INIT_DB"] = "1"

from backend.main import (
    ChatMessage,
    apply_turn_context,
    contextualize_reply_and_question,
    sanitize_reply_and_question,
    simple_extract,
)


class ChatContextTests(unittest.TestCase):
    def test_symptom_reply_is_not_treated_as_location(self):
        messages = [
            ChatMessage(role="assistant", content="事發地點在哪裡？"),
            ChatMessage(role="user", content="有人發燒了"),
        ]

        extracted = simple_extract("有人發燒了")
        updated = apply_turn_context(messages, extracted)

        self.assertEqual(updated.category, "醫療急症")
        self.assertIsNone(updated.location)

    def test_incident_detail_after_location_question_keeps_context(self):
        messages = [
            ChatMessage(role="assistant", content="事發地點在哪裡？"),
            ChatMessage(role="user", content="有人發燒了"),
        ]

        extracted = simple_extract("有人發燒了")
        extracted.location = "內埔鄉中林村中林路13巷"

        reply, next_question = contextualize_reply_and_question(
            messages,
            extracted,
            "請問事發地點在哪裡？",
            "請問事發地點在哪裡？",
            "Low",
        )

        self.assertIn("身體不舒服", reply)
        self.assertNotIn("地點是在有人發燒了", reply)
        self.assertIn("意識清楚", next_question)

    def test_sanitize_removes_redundant_location_question(self):
        extracted = simple_extract("有人發燒了")
        extracted.location = "內埔鄉中林村中林路13巷"

        reply, next_question = sanitize_reply_and_question(
            "請問事發地點在哪裡？",
            "請問事發地點在哪裡？",
            extracted,
            "Low",
        )

        self.assertNotIn("地點", next_question)
        self.assertIn("身體不舒服", reply)


if __name__ == "__main__":
    unittest.main()
