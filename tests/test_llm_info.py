"""Self-service LiteLLM views: the models you may use with prices, and your budget with clear warnings.

Run alone: uv run pytest tests/test_llm_info.py
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bootcamp_cli import llm_info  # noqa: E402

ROWS = [
    {
        "model_name": "gpt-6-luna",
        "model_info": {
            "input_cost_per_token": 1.1e-07,
            "output_cost_per_token": 5.5e-07,
            "default": True,
            "suggested": True,
            "note": "small and cheap",
            "fallback": "claude-haiku-5-5",
        },
        "litellm_params": {"model": "bedrock/converse/us.secret-backend"},
    },
    {"model_name": "claude-sonnet-5-5", "model_info": {"input_cost_per_token": 2e-06, "output_cost_per_token": 1e-05}},
    {"model_name": "internal-judge", "model_info": {}},
]


def test_models_lists_only_your_models_with_prices_and_default() -> None:
    text = "\n".join(llm_info.render_models(ROWS, {"models": ["gpt-6-luna", "claude-sonnet-5-5"]}, "gpt-6-luna"))
    assert "$0.11" in text and "$0.55" in text and "$2.00" in text and "$10.00" in text
    assert "internal-judge" not in text
    assert "us.secret-backend" in text and "bedrock/converse" not in text
    luna = text.splitlines()[1]
    assert luna.startswith("gpt-6-luna") and "YOURS" in luna and "class default" in luna and "suggested" in luna
    assert "small and cheap" in luna and "falls back to claude-haiku-5-5" in luna
    assert "YOURS" not in text.splitlines()[2] and "suggested" not in text.splitlines()[2]


def test_key_without_model_list_sees_every_model_and_unknown_price() -> None:
    text = "\n".join(llm_info.render_models(ROWS, {}, "gpt-6-luna"))
    assert "internal-judge" in text and "?" in text


def test_ranked_models_first_then_cheapest() -> None:
    def row(name: str, cost: float, rank: int | None = None) -> dict:
        return {"model_name": name, "model_info": {"input_cost_per_token": cost, "rank": rank}}

    rows = [row("cheap", 1e-08), row("pricey", 3e-06), row("second", 1e-07, 2), row("first", 2e-06, 1)]
    names = [line.split()[0] for line in llm_info.render_models(rows, {}, "")[1:5]]
    assert names == ["first", "second", "cheap", "pricey"]
    assert "MODEL_ID=cheap uv run" in llm_info.render_models(rows, {}, "")[-2]


@pytest.mark.parametrize(
    "spend, expected",
    [(0.1, "10%"), (0.8, "Over 75 % used"), (1.2, "Budget used up")],
)
def test_budget_states(spend: float, expected: str) -> None:
    text = "\n".join(llm_info.render_budget({"spend": spend, "max_budget": 1.0}))
    assert expected in text and "$" in text


def test_budget_never_shows_negative_left() -> None:
    assert "$0.000000 left" in llm_info.render_budget({"spend": 1.2, "max_budget": 1.0})[0]


def test_budget_shows_a_single_short_call() -> None:
    assert "$0.072132" in llm_info.render_budget({"spend": 0.07213195, "max_budget": 1.0})[0]


def test_budget_without_limit() -> None:
    assert "no budget limit" in llm_info.render_budget({"spend": 0.5, "max_budget": None})[0]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
