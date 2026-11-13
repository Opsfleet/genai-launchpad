Task 1 · 8 tasks
# Basic agent and prompting
Build a polite concierge whose entire knowledge of the company lives in its system prompt.
15 minEasy
Alice’s ask
## The “Simple Greeting” problem
Alice's first ask is modest: an assistant that can hold a professional conversation and knows what DataStream's departments do. No database yet, just good instructions.
You
## Build it
### Build the concierge
Challenge
Write a system prompt and create a Strands agent that answers questions about DataStream's departments (Sales, HR, Engineering) in a helpful, professional tone. It has no data yet, so it must say so instead of inventing departments or numbers.
Work in `phase1/starter/t1_basic_agent.py` (look for `TODO`; an unfinished one prints `[starter] TODO …`) and run it with `uv run bootcamp.py phase1 t1 --starter`. The reference solution is `phase1/t1_basic_agent.py`; `uv run bootcamp.py phase1 t1` runs it.
Docs
- Strands: Python quickstart (https://strandsagents.com/docs/user-guide/sdk/quickstart/python/)
- Strands: system prompts (https://strandsagents.com/docs/user-guide/sdk/agents/prompts/)
- Strands: OpenAI-compatible model provider (https://strandsagents.com/docs/user-guide/sdk/model-providers/openai/)
#### Hint 1
A Strands `Agent` is a model plus a `system_prompt` (plus tools, later). Use `make_model()` from `common.py` so calls go through the gateway. See Strands: prompts (https://strandsagents.com/docs/user-guide/sdk/agents/prompts/).
#### Hint 2
The prompt is the agent's only knowledge, so list each department with one line about what it does, then state the tone. Models fill gaps with plausible guesses, so say plainly that it has no company data yet and must never invent numbers. `common.run(agent)` gives you one-shot and chat modes.

sketch:
```python
agent = Agent(name="Concierge", model=..., system_prompt="""You are ... Our departments: ...""")
```

#### Solution: on the task page (open it only when the participant asks for the solution)
### Talk to it

terminal · your starter file:
```bash
uv run bootcamp.py phase1 t1 --starter "What departments do we have?"
uv run bootcamp.py phase1 t1 --starter "How many people work in Sales?"
```

terminal · reference solution:
```bash
uv run bootcamp.py phase1 t1 "What departments do we have?"
uv run bootcamp.py phase1 t1 "How many people work in Sales?"
```

Leave out the prompt for an interactive chat; type `exit` to quit.
### Experiments
- Add a Finance department and a rule like “always answer in two sentences”. Re-run.
- Ask about Marketing. The real company has it, but the prompt doesn't. Does the agent admit it doesn't know, or invent an answer? How would you prompt against that?
## Check your work
Phase 1 has no automated test: you check it by running the task and looking for the result below.
No `[tool]` lines: this agent has no tools. “What departments do we have?” lists Sales, HR and Engineering in a professional tone and says there are more it can't name yet. “How many people work in Sales?” gets “I don't have that data yet” (or similar), never a number.
Failed? Run the same prompt on the reference (drop `--starter`). If the reference fails too, it's the model: rerun or try another `MODEL_ID` (`uv run bootcamp.py llm models`).
#### Under the hood
Each call sends the system prompt plus the conversation so far to the model through LiteLLM. With no tools, the agent loop is a single model call. The prompt is the agent's only source of truth, which is exactly why Task 2 gives it real data.
