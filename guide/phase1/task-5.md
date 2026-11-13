Task 5 · 8 tasks
# Hooks and interrupts
Pause the agent for human approval before any destructive SQL reaches the database.
25 minMedium
Alice’s ask
## The “Rogue Agent” problem
During testing the agent cheerfully ran a `DELETE`. Alice wants a human in the loop: reads are fine, anything that changes data needs explicit approval.
You
## Build it
### Write an approval hook
Challenge
Finish `ApprovalHook`: before any `query_db` call whose SQL contains DELETE, UPDATE, INSERT, DROP, ALTER or TRUNCATE, pause and ask a human. Anything but `y` cancels the call.
Work in `phase1/starter/t5_hooks_interrupts.py` (look for `TODO`; an unfinished one prints `[starter] TODO …`) and run it with `uv run bootcamp.py phase1 t5 --starter`. The reference solution is `phase1/hooks.py`; `uv run bootcamp.py phase1 t5` runs it.
Docs
- Strands: hooks (https://strandsagents.com/docs/user-guide/sdk/agents/hooks/)
- Strands: interrupts (https://strandsagents.com/docs/user-guide/sdk/interrupts/)
#### Hint 1
Hooks are typed lifecycle callbacks. You want `BeforeToolCallEvent`, registered from a `HookProvider`. The event can `interrupt()` the agent and can cancel the tool. See Strands: hooks (https://strandsagents.com/docs/user-guide/sdk/agents/hooks/) and interrupts.
#### Hint 2
Read the tool name from `event.tool_use["name"]` and the SQL from `event.tool_use["input"]["query"]`. The interrupt's return value is the human's answer.

pseudocode:
```python
def approve(self, event):
    if <not query_db>: return
    if <destructive>:
        answer = event.interrupt("approval-required", reason={"query": query})
        if answer != "y": event.cancel_tool = "..."
```

#### Solution: on the task page (open it only when the participant asks for the solution)
### Answer the interrupt
Challenge
In the same starter file, when the agent stops for an interrupt, ask the human and resume the agent with the answers (`make_responder`).
Docs
- Strands: interrupts (https://strandsagents.com/docs/user-guide/sdk/interrupts/)
#### Hint 1
An interrupted run returns with `result.stop_reason == "interrupt"` and a list of `result.interrupts`, each with an `id`, `name` and `reason`.
#### Hint 2
Resume by calling the agent again with a list of `{"interruptResponse": {"interruptId": ..., "response": ...}}`. Loop: one answer may trigger another interrupt.
#### Solution: on the task page (open it only when the participant asks for the solution)
### Try it, safely

terminal · your starter file:
```bash
uv run bootcamp.py phase1 t5 --starter
```

terminal · reference solution:
```bash
uv run bootcamp.py phase1 t5
```

This opens a chat. Type `Delete employee with ID 5`: your hook stops the query and asks `y/N`. Answer `N` first, then ask again and answer `y`.
A one-shot run (prompt on the command line) has nobody to ask, so it auto-denies.
Task 5 adds `APPROVAL_NOTE` to the system prompt: it tells the model a human approves every destructive query, so the model calls the tool and your hook does the asking. Without it, a cautious model asks for confirmation in chat and the hook never fires.
The database is your own copy, so approving a delete only affects you. Delete `phase1/datastream_corp.db` and re-run `uv run bootcamp.py phase1 t0` for a fresh one.
### Experiments
- Keyword matching is crude. Ask “Show the updated_at column of employee 5” with the keyword version: `updated_at` contains `UPDATE`, so a harmless read asks for approval. Can you phrase a request that changes data but slips past the list? Compare with the reference (`sql_guard`).
- Why does the deployed agent in Phase 2 _block_ instead of asking? Who would answer?
## Check your work
Phase 1 has no automated test: you check it by running the task and looking for the result below.
“Delete employee with ID 5” shows a `[tool] query_db: DELETE FROM employees ...` line, then the approval question (one-shot: an `[auto-deny]` line) and `[tool] query_db (cancelled)`; the agent reports that permission was denied. Answering `y` in chat runs it instead (no `(cancelled)`). With the reference guard, reads (SELECT, EXPLAIN, read-only WITH, and schema PRAGMAs such as `PRAGMA table_info(employees)`) run without a prompt; the keyword version may also stop harmless reads that mention a keyword, such as `updated_at`.
Failed? Run the same prompt on the reference (drop `--starter`). If the reference fails too, it's the model: rerun or try another `MODEL_ID` (`uv run bootcamp.py llm models`).
#### Under the hood
Hooks are typed lifecycle callbacks (before/after model call, before/after tool call, and more). `event.interrupt()` suspends the agent loop and surfaces a named interrupt to the caller; the response you send back becomes the return value inside the hook. Setting `event.cancel_tool` skips the tool and returns your message to the model as the tool result.
