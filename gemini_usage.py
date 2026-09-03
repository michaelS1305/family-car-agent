import logging
from dataclasses import dataclass
from decimal import Decimal


# Estimated Gemini Developer API standard-tier prices in USD per 1M tokens.
# Source: https://ai.google.dev/gemini-api/docs/pricing
# These values are configuration for operational estimates, not a Google invoice.
GEMINI_PRICING_USD_PER_MILLION = {
    "gemini-3.1-flash-lite": {
        "input": Decimal("0.25"),
        "cached_input": Decimal("0.025"),
        "output_including_thinking": Decimal("1.50"),
    },
}


def _value(value, name):
    if value is None:
        return None
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


def _token_count(metadata, name):
    value = _value(metadata, name)
    return int(value) if value is not None else None


def _add_optional(current, value):
    if value is None:
        return current
    return (current or 0) + value


@dataclass
class GeminiUsageTotals:
    input_tokens: int | None = None
    output_tokens: int | None = None
    thinking_tokens: int | None = None
    cached_tokens: int | None = None
    tool_use_prompt_tokens: int | None = None
    total_tokens: int | None = None
    provider_calls: int = 0
    calls_with_metadata: int = 0

    @property
    def metadata_available(self):
        return self.calls_with_metadata > 0

    @property
    def metadata_complete(self):
        return self.provider_calls > 0 and (
            self.calls_with_metadata == self.provider_calls
        )

    def add_response(self, response):
        self.provider_calls += 1
        metadata = _value(response, "usage_metadata")
        if metadata is None:
            return False

        self.input_tokens = _add_optional(
            self.input_tokens,
            _token_count(metadata, "prompt_token_count"),
        )
        self.output_tokens = _add_optional(
            self.output_tokens,
            _token_count(metadata, "candidates_token_count"),
        )
        self.thinking_tokens = _add_optional(
            self.thinking_tokens,
            _token_count(metadata, "thoughts_token_count"),
        )
        self.cached_tokens = _add_optional(
            self.cached_tokens,
            _token_count(metadata, "cached_content_token_count"),
        )
        self.tool_use_prompt_tokens = _add_optional(
            self.tool_use_prompt_tokens,
            _token_count(metadata, "tool_use_prompt_token_count"),
        )
        self.total_tokens = _add_optional(
            self.total_tokens,
            _token_count(metadata, "total_token_count"),
        )
        self.calls_with_metadata += 1
        return True


def estimate_gemini_cost_usd(model, usage):
    """Return an operational estimate, not a Google billing amount."""
    pricing = GEMINI_PRICING_USD_PER_MILLION.get(model)
    if (
        pricing is None
        or not usage.metadata_complete
        or usage.input_tokens is None
        or usage.output_tokens is None
    ):
        return None

    # cached_content_token_count is a subset of prompt tokens. Tool-result prompt
    # tokens are reported separately by the SDK and are billed as input.
    cached_tokens = usage.cached_tokens or 0
    thinking_tokens = usage.thinking_tokens or 0
    tool_use_prompt_tokens = usage.tool_use_prompt_tokens or 0
    uncached_input = max(usage.input_tokens - cached_tokens, 0)
    billable_input = uncached_input + tool_use_prompt_tokens
    billable_output = usage.output_tokens + thinking_tokens
    cost = (
        Decimal(billable_input) * pricing["input"]
        + Decimal(cached_tokens) * pricing["cached_input"]
        + Decimal(billable_output) * pricing["output_including_thinking"]
    ) / Decimal(1_000_000)
    return cost.quantize(Decimal("0.00000001"))


def log_gemini_usage(logger, request_id, model, usage, succeeded):
    estimated_cost = estimate_gemini_cost_usd(model, usage)
    logger.info(
        "operation=gemini_usage request_id=%s model=%s succeeded=%s "
        "usage_metadata_available=%s usage_metadata_complete=%s "
        "provider_calls=%s calls_with_metadata=%s "
        "input_tokens=%s output_tokens=%s thinking_tokens=%s "
        "cached_tokens=%s tool_use_prompt_tokens=%s total_tokens=%s "
        "estimated_cost_usd=%s pricing_tier=standard "
        "estimate_is_provider_invoice=false",
        request_id,
        model,
        str(bool(succeeded)).lower(),
        str(usage.metadata_available).lower(),
        str(usage.metadata_complete).lower(),
        usage.provider_calls,
        usage.calls_with_metadata,
        usage.input_tokens,
        usage.output_tokens,
        usage.thinking_tokens,
        usage.cached_tokens,
        usage.tool_use_prompt_tokens,
        usage.total_tokens,
        str(estimated_cost) if estimated_cost is not None else None,
    )
