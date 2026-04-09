import os
import unittest

os.environ["ECARE_SKIP_INIT_DB"] = "1"

from backend.main import (  # noqa: E402
    ChatMessage,
    Extracted,
    apply_structured_risk_floor,
    contextualize_reply_and_question,
    next_question,
    sanitize_reply_and_question,
)


class MedicalContextTests(unittest.TestCase):
    def test_medical_risk_floor_promotes_breathing_difficulty_to_high(self):
        extracted = Extracted(category="醫療急症", people_injured=True)

        score, level = apply_structured_risk_floor(
            "有人發燒，而且呼吸困難",
            extracted,
            0.30,
            "Medium",
        )

        self.assertGreaterEqual(score, 0.85)
        self.assertEqual(level, "High")

    def test_medical_follow_up_does_not_ask_scene_danger(self):
        extracted = Extracted(
            category="醫療急症",
            people_injured=True,
            location="內埔鄉中林村中林路13巷",
        )

        question = next_question(extracted, "High")

        self.assertIn("立刻送醫", question)
        self.assertNotIn("還在現場", question)

    def test_medical_contextual_reply_acknowledges_breathing_difficulty(self):
        messages = [
            ChatMessage(role="assistant", content="對方現在意識清楚嗎？有呼吸困難、抽搐、昏倒，或需要立刻送醫嗎？"),
            ChatMessage(role="user", content="意識清楚，他說他呼吸困難"),
        ]
        extracted = Extracted(
            category="醫療急症",
            people_injured=True,
            location="內埔鄉中林村中林路13巷",
        )

        reply, next_question = contextualize_reply_and_question(
            messages,
            extracted,
            "請再補充一下狀況。",
            "目前危險還在持續嗎？對方或事件還在現場嗎？",
            "High",
        )
        reply, next_question = sanitize_reply_and_question(
            reply,
            next_question,
            extracted,
            "High",
        )

        self.assertIn("呼吸困難", reply)
        self.assertIn("立刻撥 119", next_question)
        self.assertNotIn("還在現場", next_question)


if __name__ == "__main__":
    unittest.main()
