import os
import unittest

os.environ["ECARE_SKIP_INIT_DB"] = "1"

from backend.main import (  # noqa: E402
    ChatMessage,
    ChatUserContext,
    Extracted,
    build_fallback_graph_query_plan,
    build_graph_user_identity,
    build_knowledge_graph_cypher,
    normalize_graph_emotion,
)


class GraphRagTests(unittest.TestCase):
    def test_build_graph_user_identity_prefers_user_id(self):
        identity = build_graph_user_identity(
            "session-1",
            ChatUserContext(user_id=12, name="王小明", phone="0912-345-678"),
        )

        self.assertIsNotNone(identity)
        self.assertEqual(identity["id"], "user:12")
        self.assertEqual(identity["name"], "王小明")

    def test_fallback_graph_plan_uses_medical_context(self):
        messages = [ChatMessage(role="user", content="有人發燒而且很不舒服")]
        conversation_state = Extracted(
            category="醫療急症",
            location=None,
            people_injured=None,
            weapon=None,
            danger_active=None,
        )

        plan = build_fallback_graph_query_plan(messages, conversation_state, None)

        self.assertEqual(plan.event_keyword, "醫療急症")
        self.assertEqual(plan.injury_keyword, "未知")
        self.assertEqual(plan.search_text, "有人發燒而且很不舒服")

    def test_build_knowledge_graph_cypher_uses_event_and_search_text(self):
        plan = build_fallback_graph_query_plan(
            [ChatMessage(role="user", content="附近失火了")],
            Extracted(category="火災"),
            None,
        )

        cypher, params = build_knowledge_graph_cypher(plan)

        self.assertIn("MATCH (e:Event)", cypher)
        self.assertEqual(params["event_keyword"], "火災")
        self.assertEqual(params["search_text"], "附近失火了")

    def test_normalize_graph_emotion_maps_panic_to_chinese(self):
        self.assertEqual(normalize_graph_emotion("panic"), "慌張")
        self.assertEqual(normalize_graph_emotion("fearful"), "害怕")


if __name__ == "__main__":
    unittest.main()
