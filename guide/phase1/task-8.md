Task 8 · 8 tasks
# Agent skills
Package company know-how as skills that the agent loads only when a question needs them.
25 minIntermediate
Alice’s ask
## The “House Rules” problem
HR has a fixed format for the headcount report, and Finance has strict rules for anything about pay. Pasting every team's rules into the system prompt makes it long, expensive and confusing. Ship each rule book as a _skill_ instead: the agent sees a one-line description of each and opens the full instructions only when a question calls for them.
You
## Build it
### Write a skill
Challenge
Turn HR's headcount rules into `phase1/starter/skills/headcount-report/SKILL.md`:
- Count active employees only.
- One row per department, including departments with nobody active (count 0).
- Columns: Department, Active employees, Share of company (%, one decimal, computed in SQL).
- Largest department first, then a **Total** row.
- Finish with the line `Source: datastream_corp.db, active employees only.`
`skills/compensation-policy/SKILL.md` next to it is a finished example; the agent gets both.
Docs
- Agent Skills: SKILL.md specification (https://agentskills.io/specification)
#### Hint 1
A skill is a folder with a `SKILL.md`: YAML frontmatter with a `name` (the folder's name, lowercase with hyphens) and a `description`, then Markdown instructions. See the Agent Skills specification (https://agentskills.io/specification).
#### Hint 2
The description is all the model sees until it loads the skill, so it decides whether the skill is ever used. Say what the skill is _and_ when to use it, e.g. “Use when asked for headcount, employee counts per department or a staffing overview.”
#### Solution: on the task page (open it only when the participant asks for the solution)
### Give the agent its skills
Challenge
Build the agent with the database tools and every skill in `SKILLS_DIR`.
Work in `phase1/starter/t8_skills.py` (look for `TODO`; an unfinished one prints `[starter] TODO …`) and run it with `uv run bootcamp.py phase1 t8 --starter`. The reference solution is `phase1/t8_skills.py`; `uv run bootcamp.py phase1 t8` runs it.
Docs
- Strands: agent skills plugin (https://strandsagents.com/docs/user-guide/sdk/plugins/skills/)
#### Hint 1
Skills come from the `AgentSkills` plugin in `strands.vended_plugins.skills`. A plugin bundles hooks and tools; this one adds the skill list to the system prompt before each call and gives the agent a `skills` tool that returns a skill’s full instructions. See Strands: agent skills (https://strandsagents.com/docs/user-guide/sdk/plugins/skills/).
#### Hint 2
Pass the folder that contains the skill folders, and hand the plugin to the agent with `plugins=[...]` (not `tools=`).
#### Solution: on the task page (open it only when the participant asks for the solution)
### Run it

terminal · your starter file:
```bash
uv run bootcamp.py phase1 t8 --starter "Give me the headcount report"
uv run bootcamp.py phase1 t8 --starter "What is Alice Chen's salary?"
uv run bootcamp.py phase1 t8 --starter "Which projects are in planning?"
```

terminal · reference solution:
```bash
uv run bootcamp.py phase1 t8 "Give me the headcount report"
uv run bootcamp.py phase1 t8 "What is Alice Chen's salary?"
uv run bootcamp.py phase1 t8 "Which projects are in planning?"
```

### Experiments
- Watch for `[tool] skills: headcount-report`: the agent loads a skill before it queries. The projects question loads none, so it pays nothing for the rules it does not need.
- Delete the “keep departments with no active employees” rule from your skill and ask for the report again. Is Research still in the table?
- Make the headcount description vague (“Reporting helper.”) and ask again. Does the agent still find the skill?
- Write a third skill, for example a `project-status` report, and ask for it. The agent code does not change.
## Check your work
Phase 1 has no automated test: you check it by running the task and looking for the result below.
**Headcount:** `[tool] skills: headcount-report`, then a `[tool] query_db` that counts `status = 'active'` (long SQL is cut at 160 characters). The table has seven rows, largest first: Engineering 481 (40.0), Sales 360 (30.0), Marketing 180 (15.0), HR 84 (7.0), Finance 60 (5.0), Operations 36 (3.0), Research 0 (0.0), then **Total 1,201**, and ends with `Source: datastream_corp.db, active employees only.` No Research row, or 483 / 362 / 1,207, means a rule was skipped.
**Salary:** `[tool] skills: compensation-policy`; no individual salary, an offer of a rounded department average instead, and the line `Compensation figures are confidential; do not forward.`
**Projects:** no `skills` line, a `[tool] query_db` with `status = 'planning'`, and exactly two projects: **Brand Refresh Initiative** and **Office Expansion Project**.
Failed? Run the same prompt on the reference (drop `--starter`). If the reference fails too, it's the model: rerun or try another `MODEL_ID` (`uv run bootcamp.py llm models`).
#### Under the hood
This is _progressive disclosure_: only each skill's name and description sit in the system prompt, and the body arrives as a tool result when the model asks for it. Prompts stay short however many skills you add, and each team can own its skill as a file in the repo. Claude Code reads the same `SKILL.md` format; this repository's `.claude/skills/` folder holds skills for working on the bootcamp itself.
