"""Settings loaded from the .env next to bootcamp.py / instructor.py (or the process environment)."""

import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
PARTICIPANT_PATTERN = re.compile(r"^[a-z][a-z0-9]{0,15}$")
DEFAULT_REGION = "us-east-1"
PROMPT_ATTACK_STRENGTHS = ("NONE", "LOW", "MEDIUM", "HIGH")
DEFAULT_PROMPT_ATTACK_STRENGTH = "MEDIUM"
DEFAULT_PII_TYPES = "EMAIL,PHONE"
PII_TYPES = frozenset(
    "ADDRESS AGE AWS_ACCESS_KEY AWS_SECRET_KEY CA_HEALTH_NUMBER CA_SOCIAL_INSURANCE_NUMBER CREDIT_DEBIT_CARD_CVV "
    "CREDIT_DEBIT_CARD_EXPIRY CREDIT_DEBIT_CARD_NUMBER DRIVER_ID EMAIL INTERNATIONAL_BANK_ACCOUNT_NUMBER IP_ADDRESS "
    "LICENSE_PLATE MAC_ADDRESS NAME PASSWORD PHONE PIN SWIFT_CODE UK_NATIONAL_HEALTH_SERVICE_NUMBER "
    "UK_NATIONAL_INSURANCE_NUMBER UK_UNIQUE_TAXPAYER_REFERENCE_NUMBER URL USERNAME US_BANK_ACCOUNT_NUMBER "
    "US_BANK_ROUTING_NUMBER US_INDIVIDUAL_TAX_IDENTIFICATION_NUMBER US_PASSPORT_NUMBER US_SOCIAL_SECURITY_NUMBER "
    "VEHICLE_IDENTIFICATION_NUMBER".split()
)
"""Bedrock Guardrails PII entity types (sensitive information filter), accepted in GUARDRAIL_PII_TYPES."""


@dataclass(frozen=True)
class Settings:
    """Everything that distinguishes one participant's run from another's."""

    participant: str
    region: str
    model_id: str
    profile: str
    role_arn: str
    enable_code_interpreter: bool = False
    enable_browser: bool = False
    enable_guardrails: bool = False
    guardrail_prompt_attack_strength: str = DEFAULT_PROMPT_ATTACK_STRENGTH
    guardrail_pii_types: str = DEFAULT_PII_TYPES
    memory_episodic: bool = False
    trust_actor_header: bool = False
    verbose: bool = False


def env_flag(name: str) -> bool:
    """True when the environment variable `name` is set to true/1/yes (case-insensitive)."""
    return os.getenv(name, "false").strip().lower() in {"true", "1", "yes"}


def drop_blank_profile() -> None:
    """`AWS_PROFILE=` (blank, as in .env.example) makes boto3 look for a profile named "" and crash."""
    if not os.environ.get("AWS_PROFILE", "").strip():
        os.environ.pop("AWS_PROFILE", None)


def resolve_region() -> str:
    """BOOTCAMP_REGION (from .env) wins, so a stray shell AWS_REGION cannot silently retarget the bootcamp."""
    return os.getenv("BOOTCAMP_REGION", "").strip() or os.getenv("AWS_REGION", "").strip() or DEFAULT_REGION


def prompt_attack_strength() -> str:
    """GUARDRAIL_PROMPT_ATTACK_STRENGTH (default MEDIUM), validated.

    Raises:
        SystemExit: The value is not NONE, LOW, MEDIUM or HIGH.
    """
    value = os.getenv("GUARDRAIL_PROMPT_ATTACK_STRENGTH", "").strip().upper() or DEFAULT_PROMPT_ATTACK_STRENGTH
    if value not in PROMPT_ATTACK_STRENGTHS:
        raise SystemExit(
            f"GUARDRAIL_PROMPT_ATTACK_STRENGTH={value!r} is invalid: use one of {', '.join(PROMPT_ATTACK_STRENGTHS)}."
        )
    return value


def pii_types() -> str:
    """GUARDRAIL_PII_TYPES as a normalised comma list (default EMAIL,PHONE; "none" = no PII masking).

    Raises:
        SystemExit: A name is not a Bedrock Guardrails PII entity type.
    """
    raw = os.getenv("GUARDRAIL_PII_TYPES", "").strip().upper() or DEFAULT_PII_TYPES
    names = [] if raw == "NONE" else list(dict.fromkeys(name.strip() for name in raw.split(",") if name.strip()))
    unknown = sorted(set(names) - PII_TYPES)
    if unknown:
        raise SystemExit(
            f"GUARDRAIL_PII_TYPES: unknown type(s) {', '.join(unknown)}; valid: {', '.join(sorted(PII_TYPES))}."
        )
    return ",".join(names)


def experiment_settings() -> dict:
    """The optional add-on and experiment switches from .env, validated (see .env.example)."""
    strength, pii = prompt_attack_strength(), pii_types()
    if strength == "NONE" and not pii and env_flag("ENABLE_GUARDRAILS"):
        raise SystemExit(
            "GUARDRAIL_PROMPT_ATTACK_STRENGTH=NONE with GUARDRAIL_PII_TYPES=none leaves the guardrail empty."
        )
    return {
        "enable_code_interpreter": env_flag("ENABLE_CODE_INTERPRETER"),
        "enable_browser": env_flag("ENABLE_BROWSER"),
        "enable_guardrails": env_flag("ENABLE_GUARDRAILS"),
        "guardrail_prompt_attack_strength": strength,
        "guardrail_pii_types": pii,
        "memory_episodic": env_flag("MEMORY_EPISODIC"),
        "trust_actor_header": env_flag("TRUST_ACTOR_HEADER"),
    }


def participant_problem(participant: str) -> str | None:
    """One-line fix for a missing or malformed PARTICIPANT, or None when it is valid."""
    if not participant:
        return (
            "PARTICIPANT is empty: set PARTICIPANT=<your bootcamp name> in .env "
            "(the lowercase name your instructor registered for you)."
        )
    if not PARTICIPANT_PATTERN.match(participant):
        return f"PARTICIPANT={participant!r} is invalid: use 1-16 lowercase letters/digits, starting with a letter."
    return None


def load_settings(env_file: Path = ROOT / ".env", require_participant: bool = True) -> Settings:
    """Read and validate settings.

    Args:
        env_file: dotenv file to load (process environment wins).
        require_participant: instructor commands run without a PARTICIPANT.

    Raises:
        SystemExit: If PARTICIPANT is required but missing or malformed.
    """
    load_dotenv(env_file)
    drop_blank_profile()
    participant = os.getenv("PARTICIPANT", "").strip().lower()
    problem = participant_problem(participant)
    if require_participant and problem:
        raise SystemExit(problem)
    return Settings(
        participant=participant,
        region=resolve_region(),
        model_id=os.getenv("MODEL_ID", "").strip(),
        profile=os.getenv("AWS_PROFILE", ""),
        role_arn=os.getenv("BOOTCAMP_ROLE_ARN", ""),
        **experiment_settings(),
        verbose=env_flag("BOOTCAMP_VERBOSE"),
    )
