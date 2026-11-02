"""`.env` experiment switches: parsed and validated by bootcamp_cli/config.py, passed to terraform by stack.py.

Run alone: uv run pytest tests/test_participant_settings.py
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bootcamp_cli import config, stack  # noqa: E402

SWITCHES = (
    "ENABLE_CODE_INTERPRETER",
    "ENABLE_BROWSER",
    "ENABLE_GUARDRAILS",
    "GUARDRAIL_PROMPT_ATTACK_STRENGTH",
    "GUARDRAIL_PII_TYPES",
    "MEMORY_EPISODIC",
    "TRUST_ACTOR_HEADER",
)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Load settings from an empty .env with only the given variables set."""
    for name in SWITCHES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PARTICIPANT", "bob")

    def load(**values: str) -> config.Settings:
        for name, value in values.items():
            monkeypatch.setenv(name, value)
        return config.load_settings(tmp_path / ".env")

    return load


def test_defaults_keep_the_shipped_stack(env) -> None:
    settings = env()
    assert settings.guardrail_prompt_attack_strength == "MEDIUM"
    assert settings.guardrail_pii_types == "EMAIL,PHONE"
    assert not settings.memory_episodic and not settings.trust_actor_header


def test_switches_are_normalised(env) -> None:
    settings = env(
        GUARDRAIL_PROMPT_ATTACK_STRENGTH=" high ",
        GUARDRAIL_PII_TYPES="email, us_social_security_number,EMAIL",
        MEMORY_EPISODIC="true",
        TRUST_ACTOR_HEADER="1",
    )
    assert settings.guardrail_prompt_attack_strength == "HIGH"
    assert settings.guardrail_pii_types == "EMAIL,US_SOCIAL_SECURITY_NUMBER"
    assert settings.memory_episodic and settings.trust_actor_header
    assert env(GUARDRAIL_PII_TYPES="none").guardrail_pii_types == ""


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"GUARDRAIL_PROMPT_ATTACK_STRENGTH": "EXTREME"}, "NONE, LOW, MEDIUM, HIGH"),
        ({"GUARDRAIL_PII_TYPES": "EMAIL,SALARY"}, "unknown type"),
        ({"GUARDRAIL_PII_TYPES": "EMAIL;rm -rf"}, "unknown type"),
        (
            {"ENABLE_GUARDRAILS": "true", "GUARDRAIL_PROMPT_ATTACK_STRENGTH": "NONE", "GUARDRAIL_PII_TYPES": "none"},
            "empty",
        ),
    ],
)
def test_invalid_switches_stop_with_a_fix(env, values: dict[str, str], message: str) -> None:
    with pytest.raises(SystemExit, match=message):
        env(**values)


def test_participant_vars_pass_every_switch(env) -> None:
    settings = env(GUARDRAIL_PROMPT_ATTACK_STRENGTH="LOW", MEMORY_EPISODIC="yes", TRUST_ACTOR_HEADER="true")
    variables = stack.participant_vars(settings, 4, "https://litellm.test", "m")
    assert "-var=guardrail_prompt_attack_strength=LOW" in variables
    assert "-var=guardrail_pii_types=EMAIL,PHONE" in variables
    assert "-var=memory_episodic=true" in variables and "-var=trust_actor_header=true" in variables


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
