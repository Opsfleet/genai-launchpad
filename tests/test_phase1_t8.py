"""Task 8 skills are valid SKILL.md files, and the starter stops at TODO 1 until its skill is written.

Run alone: uv run pytest tests/test_phase1_t8.py
"""

import sys
from pathlib import Path

import pytest
from strands.vended_plugins.skills import Skill

PHASE1 = Path(__file__).resolve().parents[1] / "phase1"
REFERENCE_SKILLS = PHASE1 / "skills"
STARTER_SKILLS = PHASE1 / "starter" / "skills"
sys.path.insert(0, str(PHASE1 / "starter"))
_excepthook = sys.excepthook
import t8_skills as starter  # noqa: E402

sys.excepthook = _excepthook
sys.path[:] = [entry for entry in sys.path if not entry.startswith(str(PHASE1))]


@pytest.mark.parametrize("skills_dir", [REFERENCE_SKILLS, STARTER_SKILLS], ids=["reference", "starter"])
def test_skills_load_with_names_matching_their_folders(skills_dir: Path) -> None:
    skills = {skill.name: skill for skill in Skill.from_directory(skills_dir)}
    assert set(skills) == {"headcount-report", "compensation-policy"}
    assert all(skill.description for skill in skills.values())


def test_reference_skills_are_finished() -> None:
    assert not [path for path in REFERENCE_SKILLS.rglob("SKILL.md") if "TODO" in path.read_text()]


def test_starter_ships_the_example_skill_unchanged() -> None:
    name = "compensation-policy/SKILL.md"
    assert (STARTER_SKILLS / name).read_text() == (REFERENCE_SKILLS / name).read_text()


def test_starter_stops_at_todo_1_until_the_skill_is_written() -> None:
    with pytest.raises(NotImplementedError, match="TODO 1"):
        starter.require_done(starter.HEADCOUNT_SKILL, "TODO 1")
    starter.require_done(REFERENCE_SKILLS / "headcount-report" / "SKILL.md", "TODO 1")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
