import unittest

from app.skills import SkillRegistry


class SkillRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = SkillRegistry()

    def test_only_two_skills_are_enabled(self) -> None:
        self.assertEqual(
            [item["name"] for item in self.registry.list()],
            ["data_qa", "database_query"],
        )

    def test_qa_skill_does_not_expose_tools(self) -> None:
        skill = self.registry.get("data_qa")
        self.assertEqual(skill.allowed_tools, ())
        self.assertEqual(skill.max_tool_calls, 0)
        self.assertEqual(skill.output_actions, ("answer",))

    def test_database_query_skill_limits_tools_and_actions(self) -> None:
        skill = self.registry.get("database_query")
        self.assertEqual(skill.max_tool_calls, 3)
        self.assertIn("query_*", skill.allowed_tools)
        self.assertEqual(skill.output_actions, ("call_tool", "clarify"))
        self.assertIn("Schema图", skill.instructions)


if __name__ == "__main__":
    unittest.main()
