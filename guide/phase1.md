Phase 1 · Build locally
# Build the agent
Nine short tasks on your laptop. You write each step in a starter file and compare it with the reference solution.
0 of 9 tasks complete
## How to run a task

terminal:
```bash
uv run bootcamp.py phase1 t2 --starter "How many employees are in Engineering?"
uv run bootcamp.py phase1 t2 "How many employees are in Engineering?"
uv run bootcamp.py phase1 t7
```

The first line runs your starter file `phase1/starter/t2_*.py`, the second the reference solution `phase1/t2_*.py`. Add a prompt in quotes for one answer, or leave it out to chat.
While a task runs you'll see two kinds of extra lines. `[tool] query_db: SELECT ...` shows every tool call and its input as it happens (set `PHASE1_SHOW_TOOLS=0` to hide them). Models that think before answering show that as a dim `[reasoning] ...` block, separate from the answer (`PHASE1_SHOW_REASONING=0` hides it). After the run, `[budget] $0.012345 of $5 used (0%), ...` shows your LiteLLM spend; it warns at 75% (`PHASE1_SHOW_BUDGET=0` hides it). With `gpt-6-luna` or `claude-haiku-5-5`, Phase 1 about $0.04-0.25 and Phase 2 with the optional pages about $0.05-0.30; `claude-sonnet-5-5` costs about 20 times more.
## Tasks
0
### Setup check
Confirm your setup, your database copy and your model access before Alice's first request lands.
The “Getting Started” challenge
20 minEasy1
### Basic agent and prompting
Build a polite concierge whose entire knowledge of the company lives in its system prompt.
The “Simple Greeting” problem
15 minEasy2
### Tools over MCP
Give the agent a key to the company database: a query_db tool served by an MCP server over stdio.
The “Hidden Vault” problem
25 minMedium3
### File sessions
Persist the conversation to disk so the agent still knows Alice after a restart.
The “Goldfish” problem
15 minEasy4
### Summarizing conversation
Keep long chats small and affordable: older turns become a running summary instead of being dropped.
The “Overflowing Context” problem
15 minEasy5
### Hooks and interrupts
Pause the agent for human approval before any destructive SQL reaches the database.
The “Rogue Agent” problem
25 minMedium6
### Structured output
Make the agent return a typed Pydantic DepartmentReport instead of a wall of text.
The “Messy Handwriting” problem
20 minMedium7
### Agents as tools
Split the work: an orchestrator routes to a data specialist and a weather specialist.
The “Overloaded Agent” problem
30 minAdvanced8
### Agent skills
Package company know-how as skills that the agent loads only when a question needs them.
The “House Rules” problem
25 minIntermediate
Continue to Phase 2
