"""Self-service views of your LiteLLM access: `bootcamp.py llm models` and `bootcamp.py llm budget`.

Both read live from the gateway with your own identity (`/model/info`, `/key/info`), so they show exactly what the
gateway will let you call, which Bedrock model answers each name, what it charges you, and the instructor's
suggestions, known quirks and fallbacks (the roster's "models" entries, rendered into each model's `model_info`).
"""

PER_MILLION = 1_000_000
WARN_RATIO = 0.75


def your_models(model_rows: list[dict], key: dict) -> list[dict]:
    """The gateway's models your key may call (a key without a model list may call them all)."""
    allowed = set(key.get("models") or [])
    return [row for row in model_rows if not allowed or row["model_name"] in allowed]


def price(row: dict, kind: str) -> str:
    """USD per million tokens of `kind` ("input" or "output"), or "?" when the gateway has no price."""
    per_token = (row.get("model_info") or {}).get(f"{kind}_cost_per_token")
    return "?" if per_token is None else f"${per_token * PER_MILLION:.2f}"


def backend(row: dict) -> str:
    """The Bedrock model that answers a gateway model name (LiteLLM's `bedrock/converse/` prefix dropped)."""
    model = (row.get("litellm_params") or {}).get("model", "?")
    return model.removeprefix("bedrock/").removeprefix("converse/")


def remarks(row: dict, mine: str) -> str:
    """Yours / class default / suggested, the instructor's note, and the fallback model, if any."""
    info = row.get("model_info") or {}
    tags = [
        "YOURS" if row["model_name"] == mine else "",
        "class default" if info.get("default") else "",
        "suggested" if info.get("suggested") else "",
        info.get("note") or "",
        f"falls back to {info['fallback']} (at its price)" if info.get("fallback") else "",
    ]
    return "; ".join(tag for tag in tags if tag)


def listing_order(row: dict) -> tuple:
    """The instructor's ranked models first (roster `rank`), then the rest from cheapest input price up."""
    info = row.get("model_info") or {}
    rank, cost = info.get("rank"), info.get("input_cost_per_token")
    return (rank is None, rank or 0, cost is None, cost or 0.0, row["model_name"])


def render_models(model_rows: list[dict], key: dict, mine: str) -> list[str]:
    """One line per model you may use: name, Bedrock model, price per million tokens, then remarks."""
    rows = sorted(your_models(model_rows, key), key=listing_order)
    name_width = max([len(row["model_name"]) for row in rows] + [len("MODEL_ID")])
    width = max([len(backend(row)) for row in rows] + [len("BEDROCK MODEL")])
    header = f"{'MODEL_ID':<{name_width}}  {'BEDROCK MODEL':<{width}} {'INPUT /1M':>10} {'OUTPUT /1M':>11}  NOTES"
    lines = [header]
    for row in rows:
        prices = f"{price(row, 'input'):>10} {price(row, 'output'):>11}"
        lines.append(f"{row['model_name']:<{name_width}}  {backend(row):<{width}} {prices}  {remarks(row, mine)}")
    example = min(rows, key=lambda row: listing_order(row)[2:])["model_name"] if rows else "<model>"
    notes = [
        f"Pick any MODEL_ID above: in .env, or for one command (MODEL_ID={example} uv run bootcamp.py ...).",
        "Without MODEL_ID you get the class default. Prices are per million tokens, charged to your budget.",
    ]
    return [*lines, *notes]


def render_budget(key: dict) -> list[str]:
    """Spent, limit, left and percent used; a warning from 75 % and a clear line when it is used up."""
    spent, limit = float(key.get("spend") or 0.0), key.get("max_budget")
    if limit is None:
        return [f"Spent ${spent:.6f}; no budget limit on your key."]
    used = spent / limit if limit else 1.0
    lines = [f"Spent ${spent:.6f} of ${limit:g} ({used:.0%}); ${max(limit - spent, 0.0):.6f} left."]
    if used >= 1:
        lines.append("Budget used up: model calls now fail with HTTP 429. Ask your instructor for a top-up.")
    elif used >= WARN_RATIO:
        lines.append("Over 75 % used: switch to a cheaper model (`llm models`) or ask your instructor for a top-up.")
    if key.get("budget_reset_at"):
        lines.append(f"Resets at {key['budget_reset_at']}.")
    return [*lines, "Spend can lag a few seconds behind your last call."]
