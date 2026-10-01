"""Real Pydantic validation tests; runnable without FastAPI or a database."""
import unittest

from pydantic import ValidationError
from app.schemas import ChatRequest, DocumentCreate, PluginCreate, PluginUpdate, RepairCreate


class SchemaTests(unittest.TestCase):
    def test_trimmed_text_and_rejected_blank(self):
        self.assertEqual(ChatRequest(message="  一卡通  ").message, "一卡通")
        for cls, data in ((ChatRequest, {"message": "  "}), (DocumentCreate, {"title": "  ", "content": "text"}),
                          (RepairCreate, {"location": "  ", "issue": "     ", "contact": "xx"})):
            with self.subTest(cls=cls), self.assertRaises(ValidationError):
                cls(**data)

    def test_invalid_model_and_extra_fields_are_rejected(self):
        for data in ({"message": "hello", "model": "untrusted"}, {"message": "hello", "execute": "shell"}):
            with self.assertRaises(ValidationError):
                ChatRequest(**data)

    def test_plugin_null_patch_cannot_corrupt_database(self):
        self.assertEqual(PluginUpdate(enabled=False).enabled, False)
        self.assertEqual(PluginUpdate().model_dump(exclude_unset=True), {})
        for data in ({"enabled": None}, {"description": None}, {"description": "  "}):
            with self.assertRaises(ValidationError):
                PluginUpdate(**data)

    def test_plugin_schema_validation(self):
        base = {"name": "campus_map", "description": "校园地图", "url": "https://plugins.example.edu/map"}
        self.assertEqual(PluginCreate(**base).name, "campus_map")
        with self.assertRaises(ValidationError):
            PluginCreate(**base, parameters={"properties": {"payload": {"type": "object"}}})


if __name__ == "__main__":
    unittest.main()
