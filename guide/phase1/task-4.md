Task 4 · 8 tasks
# Summarizing conversation
Keep long chats small and affordable: older turns become a running summary instead of being dropped.
15 minEasy
Alice’s ask
## The “Overflowing Context” problem
Conversations grow, context windows don't, and every token costs budget. Simply dropping old messages makes the assistant forget what Alice told it. Instead, fold the older turns into a short summary and keep only the latest ones verbatim.
You
## Build it
### Summarize older turns, keep the last two verbatim
Challenge
Keep a session as in Task 3, but when the context gets full, replace the oldest messages with a summary and keep the 2 most recent messages as they are, and make sure the summary keeps what the user told the agent. The starter already gives the model a deliberately tiny 1,000-token context window, so you see it happen within a few messages.
Work in `phase1/starter/t4_conversation.py` (look for `TODO`; an unfinished one prints `[starter] TODO …`) and run it with `uv run bootcamp.py phase1 t4 --starter`. The reference solution is `phase1/t4_conversation.py`; `uv run bootcamp.py phase1 t4` runs it.
Docs
- Strands: conversation management (SummarizingConversationManager) (https://strandsagents.com/docs/user-guide/sdk/agents/conversation-management/#summarizingconversationmanager)
#### Hint 1
Storage and context are separate concerns in Strands. Context is handled by a _conversation manager_. Strands: conversation management (https://strandsagents.com/docs/user-guide/sdk/agents/conversation-management/).
#### Hint 2
Import `SummarizingConversationManager` from `strands.agent.conversation_manager`. Keep 2 recent messages (`preserve_recent_messages=2`), summarize most of the rest in one go (`summary_ratio=0.8`, the maximum), and turn on `proactive_compression={"compression_threshold": 0.7}` so it summarizes once the context is 70% full instead of waiting for an overflow error.
#### Hint 3
Strands' default summary prompt lists topics and tool results and can drop personal facts. Pass your own with `summarization_system_prompt=`, telling it to keep every fact the user stated about themselves.
#### Solution: on the task page (open it only when the participant asks for the solution)
### Chat until it summarizes

terminal · your starter file:
```bash
uv run bootcamp.py phase1 t4 --starter
```

terminal · reference solution:
```bash
uv run bootcamp.py phase1 t4
```

Start from a fresh session: add a new session name, e.g. `uv run bootcamp.py phase1 t4 --starter --session colors1` (next try `colors2`), then type, one at a time: `My favorite color is blue`, `List every department with its budget and number of active employees`, `My favorite food is pizza`, `I live in Haifa`, `What is my favorite color?`. Then keep chatting: a few more messages fit before the next summary.
The system prompt and the tool description take about 340 tokens with the suggested model (another tokenizer counts differently). The department table brings the prompt to about 650, and a message or two later it passes the 700-token threshold (70%). Then, before the next model call, the manager asks the model to summarize the oldest messages and prints `[context] prompt ~710 of 1,000 tokens: older messages summarized (N so far, M kept)`, followed by the summary itself: the bullet points that now stand in for the older messages. Each later summary includes the previous one.
The two numbers work together: a summary has to bring the prompt well under the threshold. With a low threshold and a small ratio, the prompt after a summary is still over the line, so the manager summarizes again before every model call.
On the very first message you may see `Proactive summarization failed, continuing: Cannot summarize: insufficient messages`. It is harmless: before the model has reported real usage, Strands estimates the prompt at about 4 characters per token, which overshoots, and there is nothing to summarize yet. From the second call on it uses the token counts the model reports.
### Experiments
- Open `phase1/sessions/session_summary_session/` (`session_summary_session_starter/` for your starter file): the session on disk still has every message, only the model's context was summarized.
- Swap in `SlidingWindowConversationManager(window_size=2)` and repeat in a fresh session (a new `--session` name). Now the `[context]` line says _dropped_ and the agent forgets blue: a window drops old turns, a summary keeps their gist. (A warning that it found no valid trim point during the database question is expected: a window never splits a tool call from its result.)
- Set `summary_ratio=0.5` and `compression_threshold` to 0.5 and repeat in a fresh session: the `[context]` line now appears before nearly every model call, each one an extra summarization call you pay for.
- Remove `summarization_system_prompt` to get Strands' default summary and repeat. Read the summary in the session's `agent.json`: is your favorite color still in it?
- Raise `CONTEXT_WINDOW_TOKENS` to 200,000 (realistic). No `[context]` line in a short chat: summarization costs an extra model call, so it only runs when it pays off.
- Run `uv run bootcamp.py llm` before and after a long chat to see what the extra summary calls cost.
## Check your work
Phase 1 has no automated test: you check it by running the task and looking for the result below.
A message or two after the department question you see one `[context] ... older messages summarized` line (none before it), and “What is my favorite color?” still gets **blue**: the agent reads it from the summary printed under the `[context]` line (look for blue there), not from the original message. No `[context]` line at all? Start from a fresh session and check `CONTEXT_WINDOW_TOKENS` is 1,000.
Failed? Run the same prompt on the reference (drop `--starter`). If the reference fails too, it's the model: rerun or try another `MODEL_ID` (`uv run bootcamp.py llm models`).
#### Under the hood
Before each model call the manager estimates the prompt size: the previous call's real token count (system prompt and tool descriptions included) plus an estimate for the messages added since. Past the threshold (`compression_threshold` × `context_window_limit`) it sends the oldest messages to the model with a summarization prompt and swaps them for one summary message, never splitting a tool call from its result. The session manager still stores everything on disk: _storage_ and _context_ are separate decisions. In Phase 2, AgentCore Memory's summary strategy does the same across sessions, on the server.
