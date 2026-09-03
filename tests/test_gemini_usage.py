from decimal import Decimal
import logging
import unittest

from gemini_usage import (
    GeminiUsageTotals,
    estimate_gemini_cost_usd,
    log_gemini_usage,
)


class Response:
    def __init__(self, usage_metadata=None):
        self.usage_metadata = usage_metadata


class GeminiUsageTests(unittest.TestCase):
    def test_simple_response_usage(self):
        usage = GeminiUsageTotals()

        added = usage.add_response(Response({
            "prompt_token_count": 100,
            "candidates_token_count": 20,
            "total_token_count": 120,
        }))

        self.assertTrue(added)
        self.assertEqual(usage.input_tokens, 100)
        self.assertEqual(usage.output_tokens, 20)
        self.assertEqual(usage.total_tokens, 120)
        self.assertEqual(usage.calls_with_metadata, 1)

    def test_multi_call_tool_flow_accumulates_usage(self):
        usage = GeminiUsageTotals()
        usage.add_response(Response({
            "prompt_token_count": 100,
            "candidates_token_count": 10,
            "tool_use_prompt_token_count": 5,
            "total_token_count": 115,
        }))
        usage.add_response(Response({
            "prompt_token_count": 150,
            "candidates_token_count": 30,
            "tool_use_prompt_token_count": 8,
            "total_token_count": 188,
        }))

        self.assertEqual(usage.input_tokens, 250)
        self.assertEqual(usage.output_tokens, 40)
        self.assertEqual(usage.tool_use_prompt_tokens, 13)
        self.assertEqual(usage.total_tokens, 303)
        self.assertEqual(usage.calls_with_metadata, 2)

    def test_missing_usage_metadata_does_not_invent_usage_or_cost(self):
        usage = GeminiUsageTotals()

        self.assertFalse(usage.add_response(Response()))
        self.assertFalse(usage.metadata_available)
        self.assertFalse(usage.metadata_complete)
        self.assertIsNone(usage.input_tokens)
        self.assertIsNone(usage.total_tokens)
        self.assertIsNone(
            estimate_gemini_cost_usd("gemini-3.1-flash-lite", usage)
        )

    def test_failure_without_metadata_keeps_prior_usage_but_skips_cost(self):
        usage = GeminiUsageTotals()
        usage.add_response(Response({
            "prompt_token_count": 100,
            "candidates_token_count": 20,
            "total_token_count": 120,
        }))
        usage.add_response(None)

        self.assertEqual(usage.input_tokens, 100)
        self.assertEqual(usage.total_tokens, 120)
        self.assertFalse(usage.metadata_complete)
        self.assertIsNone(
            estimate_gemini_cost_usd("gemini-3.1-flash-lite", usage)
        )

    def test_thinking_and_cached_tokens_are_reported_and_priced(self):
        usage = GeminiUsageTotals()
        usage.add_response(Response({
            "prompt_token_count": 1_000_000,
            "cached_content_token_count": 200_000,
            "candidates_token_count": 100_000,
            "thoughts_token_count": 50_000,
            "total_token_count": 1_150_000,
        }))

        self.assertEqual(usage.thinking_tokens, 50_000)
        self.assertEqual(usage.cached_tokens, 200_000)
        self.assertEqual(
            estimate_gemini_cost_usd("gemini-3.1-flash-lite", usage),
            Decimal("0.43000000"),
        )

    def test_safe_logging_excludes_message_and_api_key(self):
        usage = GeminiUsageTotals()
        usage.add_response(Response({
            "prompt_token_count": 10,
            "candidates_token_count": 5,
            "total_token_count": 15,
        }))
        logger = logging.getLogger("test.gemini.usage")

        with self.assertLogs(logger, level="INFO") as captured:
            log_gemini_usage(
                logger,
                "request-safe-id",
                "gemini-3.1-flash-lite",
                usage,
                True,
            )

        line = captured.output[0]
        self.assertIn("operation=gemini_usage", line)
        self.assertIn("request_id=request-safe-id", line)
        self.assertNotIn("private family message", line)
        self.assertNotIn("private-api-key", line)


if __name__ == "__main__":
    unittest.main()
