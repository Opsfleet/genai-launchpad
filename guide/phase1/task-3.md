Task 3 · 8 tasks
# File sessions
Persist the conversation to disk so the agent still knows Alice after a restart.
15 minEasy
Alice’s ask
## The “Goldfish” problem
Alice introduced herself. One restart later the agent greeted her like a stranger. Give it short-term memory that survives the process.
You
## Build it
### Make the conversation survive a restart
Challenge
Give the Task 2 agent a session that is saved under `SESSIONS_DIR` with the id `SESSION_ID` (`alice_session_starter` in your starter, `alice_session` in the reference, so the reference never fills in your starter's memory).
Work in `phase1/starter/t3_sessions.py` (look for `TODO`; an unfinished one prints `[starter] TODO …`) and run it with `uv run bootcamp.py phase1 t3 --starter`. The reference solution is `phase1/t3_sessions.py`; `uv run bootcamp.py phase1 t3` runs it.
Docs
- Strands: session management (https://strandsagents.com/docs/user-guide/sdk/agents/session-management/)
#### Hint 1
Strands has session managers that plug into the agent lifecycle. Look at `strands.session.FileSessionManager`. See Strands: session management (https://strandsagents.com/docs/user-guide/sdk/agents/session-management/).
#### Hint 2
Create it once, before the agent, and pass it as `session_manager=`.

sketch:
```python
session_manager = FileSessionManager(session_id=..., storage_dir=str(SESSIONS_DIR))
```

#### Solution: on the task page (open it only when the participant asks for the solution)
### Introduce yourself, then restart

terminal · your starter file:
```bash
uv run bootcamp.py phase1 t3 --starter "My name is Alice Chen, CEO of DataStream Corp"
uv run bootcamp.py phase1 t3 --starter "What's my name?"
```

terminal · reference solution:
```bash
uv run bootcamp.py phase1 t3 "My name is Alice Chen, CEO of DataStream Corp"
uv run bootcamp.py phase1 t3 "What's my name?"
```

Two separate processes, one memory. Look at what was stored:

terminal:
```bash
ls phase1/sessions/session_alice_session_starter/agents/agent_default/messages/   # your starter
ls phase1/sessions/session_alice_session/agents/agent_default/messages/           # reference
```

To start over, pass a new session name: `--session alice2` (any letters, digits, `_` or `-`) starts an empty session, and the run prints `[session] ...` so you always see which one you are in. Deleting a session's folder works too.
### Experiments
- Open a `message_*.json` file. What exactly is persisted?
- Play two users: introduce yourself as Bob with `--session bob`, then ask `--session bob "What's my name?"` and the same without `--session`. Now run both people on one shared session name: each sees the other's history. That's the isolation problem AgentCore Memory solves in Phase 2.
## Check your work
Phase 1 has no automated test: you check it by running the task and looking for the result below.
In the second process, “What's my name?” answers **Alice Chen** without a `[tool]` line: the name comes from the restored history, not the database. JSON message files appear under `phase1/sessions/session_alice_session_starter/` (reference: `session_alice_session/`). If your starter remembers nothing, check that it saves to `SESSION_ID`.
Failed? Run the same prompt on the reference (drop `--starter`). If the reference fails too, it's the model: rerun or try another `MODEL_ID` (`uv run bootcamp.py llm models`).
#### Under the hood
`FileSessionManager` hooks into the agent lifecycle: it restores messages when the agent is created and appends every new message as a JSON file. It's ideal for local work and useless for a fleet of containers, which is why Phase 2 swaps it for `AgentCoreMemorySessionManager` with almost the same call site.
