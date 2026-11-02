"""The participant's own terraform stack: where it lives and the variables every apply/destroy passes."""

from bootcamp_cli.build import BUILD_DIR
from bootcamp_cli.config import ROOT, Settings

PARTICIPANT_DIR = ROOT / "terraform" / "participant"


def participant_vars(settings: Settings, stage: int, litellm_base_url: str = "", model_id: str = "") -> list[str]:
    """`-var=` flags for the participant stack.

    Args:
        settings: The participant's settings (name, region, model, optional tools).
        stage: Highest stage to provision (0..7).
        litellm_base_url: The LiteLLM gateway URL the agent runtime calls (empty for destroy).
        model_id: Gateway model the agent uses (defaults to settings.model_id; unused by destroy).

    Returns:
        One `-var=key=value` argument per variable.
    """
    values = {
        "participant": settings.participant,
        "stage": stage,
        "aws_region": settings.region,
        "model_id": model_id or settings.model_id,
        "build_dir": BUILD_DIR.as_posix(),
        "litellm_base_url": litellm_base_url,
        "enable_code_interpreter": str(settings.enable_code_interpreter).lower(),
        "enable_browser": str(settings.enable_browser).lower(),
        "enable_guardrails": str(settings.enable_guardrails).lower(),
        "guardrail_prompt_attack_strength": settings.guardrail_prompt_attack_strength,
        "guardrail_pii_types": settings.guardrail_pii_types,
        "memory_episodic": str(settings.memory_episodic).lower(),
        "trust_actor_header": str(settings.trust_actor_header).lower(),
    }
    return [f"-var={key}={value}" for key, value in values.items()]
