import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "compact_tune.py"
SPEC = importlib.util.spec_from_file_location("compact_tune", SCRIPT)
compact_tune = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compact_tune)


def token_count(ordinal, input_tokens, cached_input_tokens, window=258400):
    usage = {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "cache_write_input_tokens": 0,
        "output_tokens": 100,
    }
    return {
        "ordinal": ordinal,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "last_token_usage": usage,
                "model_context_window": window,
            },
        },
    }


def usage_record(ordinal, input_tokens, cached_input_tokens, response_id):
    return {
        "ordinal": ordinal,
        "type": "token_usage_record",
        "payload": {
            "response_id": response_id,
            "usage": {
                "input_tokens": input_tokens,
                "cached_input_tokens": cached_input_tokens,
                "cache_write_input_tokens": 0,
                "output_tokens": 100,
            },
        },
    }


class CodexParserTests(unittest.TestCase):
    def write_rollout(self, records):
        handle = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        with handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")
        return handle.name

    def test_legacy_token_count_records_include_compaction_boundary(self):
        path = self.write_rollout([
            token_count(1, 100, 80),
            token_count(2, 0, 0),
            {"ordinal": 3, "type": "event_msg", "payload": {
                "type": "item_completed",
                "item": {"type": "ContextCompaction"},
            }},
            token_count(4, 1000, 200),
        ])

        sequence = compact_tune.parse_codex(path)

        self.assertEqual([kind for kind, _, _ in sequence], ["A", "C", "A"])
        self.assertEqual(sequence[0][1].ctx, 100)
        self.assertEqual(sequence[1][1], 100)
        self.assertEqual(sequence[2][1].ctx, 1000)

    def test_new_records_are_not_double_counted_with_token_count_events(self):
        path = self.write_rollout([
            usage_record(1, 100, 80, "resp-1"),
            token_count(2, 100, 80),
            token_count(3, 0, 0),
            {"ordinal": 4, "type": "event_msg", "payload": {
                "type": "item_completed",
                "item": {"type": "ContextCompaction"},
            }},
            usage_record(5, 120, 80, "resp-2"),
            token_count(6, 120, 80),
        ])

        sequence = compact_tune.parse_codex(path)

        self.assertEqual([kind for kind, _, _ in sequence], ["A", "C", "A"])
        self.assertEqual(sequence[0][1].rid, "resp-1")
        self.assertEqual(sequence[1][1], 100)
        self.assertEqual(sequence[2][1].rid, "resp-2")


if __name__ == "__main__":
    unittest.main()
