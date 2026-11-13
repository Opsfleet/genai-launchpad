Task 7 · 8 tasks
# Agents as tools
Split the work: an orchestrator routes to a data specialist and a weather specialist.
30 minAdvanced
Alice’s ask
## The “Overloaded Agent” problem
Alice now wants headcounts _and_ the weather for her next business trip. One agent with every tool and every instruction gets confused. Build a small team instead.
You
## Build it
### Build the team
Challenge
Create two specialists, `data_agent` (database tools plus the approval hook) and `weather_agent` (forecasts for US locations from the National Weather Service), and an orchestrator that routes to them.
Work in `phase1/starter/t7_agents_as_tools.py` (look for `TODO`; an unfinished one prints `[starter] TODO …`) and run it with `uv run bootcamp.py phase1 t7 --starter`. The reference solution is `phase1/t7_agents_as_tools.py`; `uv run bootcamp.py phase1 t7` runs it.
Docs
- Strands: agents as tools (https://strandsagents.com/docs/user-guide/sdk/multi-agent/agents-as-tools/)
- Strands: hooks (https://strandsagents.com/docs/user-guide/sdk/agents/hooks/)
#### Hint 1
Any function decorated with `@tool` is a tool, so a function that runs another agent is one too. This is the “agents as tools” pattern. See Strands: agents as tools (https://strandsagents.com/docs/user-guide/sdk/multi-agent/agents-as-tools/).
#### Hint 2
Each specialist gets its own prompt and tools; its docstring tells the orchestrator when to use it. The weather agent's tool, `get_us_forecast` in `shared/nws_weather.py`, is ready-made: import it with `WEATHER_PROMPT`.

sketch:
```python
@tool
def data_agent(query: str) -> str:
    """<when to use me>"""
    return str(Agent(model=..., system_prompt=..., tools=db_tools, hooks=[...])(query))
```

#### Solution: on the task page (open it only when the participant asks for the solution)
### Run it

terminal · your starter file:
```bash
uv run bootcamp.py phase1 t7 --starter "How many employees are in Engineering?"
uv run bootcamp.py phase1 t7 --starter "What is the weather in Seattle?"
uv run bootcamp.py phase1 t7 --starter "How many employees do we have and what is the weather in New York?"
uv run bootcamp.py phase1 t7 --starter "What is the weather in London?"
```

terminal · reference solution:
```bash
uv run bootcamp.py phase1 t7 "How many employees are in Engineering?"
uv run bootcamp.py phase1 t7 "What is the weather in Seattle?"
uv run bootcamp.py phase1 t7 "How many employees do we have and what is the weather in New York?"
uv run bootcamp.py phase1 t7 "What is the weather in London?"
```

### Experiments
- Watch the `[tool] data_agent: ...` / `[tool] weather_agent: ...` lines, followed by the specialists' own `[tool] query_db` / `[tool] get_us_forecast` lines: what question does the orchestrator actually pass down?
- Try a stronger model from `uv run bootcamp.py llm models` (`MODEL_ID=<model>`) for the combined question, then check `uv run bootcamp.py llm`. Was the better routing worth the spend?
- Add a third specialist, for example one that returns a `DepartmentReport`.
## Check your work
Phase 1 has no automated test: you check it by running the task and looking for the result below.
“How many employees are in Engineering?” shows `[tool] data_agent: ...` followed by the specialist's `[tool] query_db` (filtering `status = 'active'`) and answers **481**. “What is the weather in Seattle?” shows `[tool] weather_agent` and `[tool] get_us_forecast`, no `query_db`. The combined question shows both specialist lines and one answer with **1,201** employees and the New York forecast. London gets the weather agent's US-only sentence instead of a forecast.
The LiteLLM gateway already retries a model reply that carries no answer and then falls back to the model's fallback, if it has one (`llm models` shows it), so empty turns are rare. A specialist that still fails shows up as “The data specialist failed: ...” in the answer instead of made-up numbers. If the orchestrator itself ends with an empty answer, the script prints `[fallback] Empty final answer (try another MODEL_ID); last specialist result:` followed by that result. If it happens often, set `MODEL_ID` in `.env` to another model from `llm models` and re-run.
Failed? Run the same prompt on the reference (drop `--starter`). If the reference fails too, it's the model: rerun or try another `MODEL_ID` (`uv run bootcamp.py llm models`).
#### Under the hood
A `@tool` is a function with a schema derived from its signature and docstring, so a function that runs another agent is a tool too. Each specialist has its own prompt, tools and context, which keeps prompts short and failures contained. This orchestrator is what you deploy to AgentCore Runtime in Phase 2, Task 4.
