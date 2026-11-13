Task 3 · 8 tasks
# AgentCore Memory
Long-term, per-user memory that learns facts across sessions and keeps users apart.
15 minEasy
Alice’s ask
## The “Remember Me, Not Jordan” crisis
Alice is frustrated: “I told the agent last week I prefer Python reports, and today it forgot. Worse, Jordan could see my preferences!” File sessions on one laptop won't cut it. You need memory that persists across sessions _and_ is isolated per user.
Platform
## What the platform provisions for you

terminal:
```bash
uv run bootcamp.py up 3
```

- An AgentCore Memory resource with three extraction strategies: **UserFacts** (semantic), **UserPreferences** (user preference) and **SessionSummaries** (summary)
- Its `MEMORY_ID` and one id per strategy (`MEMORY_STRATEGY_ID`, `MEMORY_PREFERENCE_STRATEGY_ID`, `MEMORY_SUMMARY_STRATEGY_ID`), visible in `status` and injected into the agent in Task 4
Adding this stage usually takes **~11 min**; the CLI prints progress (and full terraform output with `--verbose`).
**While you wait**
Memory creation is most of these minutes. Read the first two steps below (who is calling, short-term vs long-term), and open **AgentCore → Memory** (https://us-east-1.console.aws.amazon.com/bedrock-agentcore/memory?region=us-east-1) in the console to watch your memory go from `CREATING` to `ACTIVE`.
You
## What you do as a developer
### Read the code: who is calling?
Memory is partitioned by _actor_, so the actor must be the person really calling. `invoke --actor alice-chen` signs in as Alice (Task 0) and sends her access token; the runtime's JWT authorizer validates it (Task 4), and the agent reads the actor from its `username` claim.

phase2/app/agent/agent.py:
```python
ACTOR_CLAIM = "username"
"""Cognito puts the signed-in user's name in this claim of its access tokens (M2M client tokens have none)."""

def actor_from(context: RequestContext) -> str:
    """The signed-in user, from the verified token: never trust caller-supplied identity (a header anyone can set).

    Raises:
        PermissionError: The token names no user (e.g. a machine-to-machine client token).
    """
    actor = insecure_header_actor(context) or token_claims(context).get(ACTOR_CLAIM)
    if not actor:
        raise PermissionError(f"the bearer token has no '{ACTOR_CLAIM}' claim: sign in as a user")
    return str(actor)

def token_claims(context: RequestContext) -> dict:
    """The claims of the request's bearer token ({} when there is none).

    Decoding without checking the signature is safe only because the runtime's JWT authorizer already verified the
    signature, issuer, expiry and client before the request reached this code.
    """
    headers = {name.lower(): value for name, value in (context.request_headers or {}).items()}
    token = headers.get("authorization", "").split(" ")[-1]
    try:
        payload = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return {}
```

**Question:** The original guide took the actor from a header the caller sets (`X-Amzn-Bedrock-AgentCore-Runtime-Custom-Actor-Id`). What was wrong with that?
#### Answer
Anyone allowed to invoke the agent could type any name into that header and read that user's memories: Jordan sends `alice-chen` and gets Alice's preferences, exactly Alice's “Jordan could see my preferences” bug. A token is different: Cognito signs it, so its `username` cannot be changed without breaking the signature. **Never trust caller-supplied identity**; take it from something the platform verified.
**Question:** `token_claims` decodes the token without checking its signature. Isn't that the same mistake?
#### Answer
No, because of where it runs. The runtime's authorizer has already verified the signature, issuer, expiry and client before the request reaches your code, and only the `Authorization` header is forwarded. The same decode in a service with no authorizer in front would be a hole.
### Short-term vs long-term memory
AgentCore Memory has two layers, and your agent uses both:
- **Short-term**: every turn is stored as an _event_ under an actor and a session (`CreateEvent`, read back with `ListEvents`). Continuing a session (`--session last`) reloads its turns: the conversation so far, exact and immediate.
- **Long-term**: _strategies_ read those events in the background and extract _records_ into namespaces (about 1-2 minutes later). Before each model call the agent searches them (`RetrieveMemoryRecords`, with your question as the query) and gets the hits as `<user_context>`, even in a brand-new session.
Short-term events vs long-term records. Solid arrows are calls, the dotted arrow is background extraction; cyan-bordered boxes are the two ways an invocation reads memory back.
StrategyTypeExtractsNamespaceIn your stack
Semantic`SEMANTIC`Facts (“Alice owns the Q3 report”)per actorDeployed: UserFacts
User preference`USER_PREFERENCE`Choices and style (“answers in French”, “numbers in thousands”)per actorDeployed: UserPreferences
Summary`SUMMARIZATION`A running summary of one session, by topicper actor and sessionDeployed: SessionSummaries
Episodic`EPISODIC`Episodes (goal, steps, outcome) plus reflections across themper actor (and session)Not deployed: more extraction calls per turn; try it in Experiments
Custom / self-managed`CUSTOM`A built-in strategy with your own extraction/consolidation prompt and model (override), or your own pipeline fed by events (self-managed)you chooseNot deployed: needs a memory execution role (override) or your own SNS/S3 pipeline
Each strategy writes to its own namespace, built from its template: `/strategies/{memoryStrategyId}/actors/{actorId}` for facts and preferences, plus `/sessions/{sessionId}` for summaries. The actor id in the path is what keeps Alice's records away from Jordan's, as long as you search by _path_: `namespacePath=.../actors/pat` matches `pat` and `pat/sessions/...`, while the older `namespace=` parameter is a plain string prefix that also matches `pat-x`. The Strands session manager and `bootcamp.py memory` use `namespacePath`.
### Read the code: what the agent retrieves

phase2/app/agent/agent.py:
```python
MEMORY_RELEVANCE_SCORE = 0.3
"""Minimum relevance a long-term fact or past-session summary needs to be retrieved into the conversation."""

ALWAYS = 0.0
"""No relevance threshold: preferences (language, format, units) apply to every question, whatever it is."""

def long_term_retrieval() -> dict[str, RetrievalConfig]:
    """Which long-term records to search before each model call: one namespace prefix per strategy, per actor.

    The session manager fills in {actorId}; a namespace is a path prefix, so the summary entry covers every past
    session of this actor (`.../sessions/<id>`).
    """
    return {
        f"/strategies/{MEMORY_STRATEGY_ID}/actors/{{actorId}}": RetrievalConfig(
            top_k=5, relevance_score=MEMORY_RELEVANCE_SCORE
        ),
        f"/strategies/{MEMORY_PREFERENCE_STRATEGY_ID}/actors/{{actorId}}": RetrievalConfig(
            top_k=5, relevance_score=ALWAYS
        ),
        f"/strategies/{MEMORY_SUMMARY_STRATEGY_ID}/actors/{{actorId}}": RetrievalConfig(
            top_k=2, relevance_score=MEMORY_RELEVANCE_SCORE
        ),
    }

def memory_session_manager(session_id: str, actor_id: str) -> AgentCoreMemorySessionManager:
    """Short-term: this session's turns (events). Long-term: this actor's facts, preferences and session summaries."""
    config = AgentCoreMemoryConfig(
        memory_id=MEMORY_ID, session_id=session_id, actor_id=actor_id, retrieval_config=long_term_retrieval()
    )
    return AgentCoreMemorySessionManager(agentcore_memory_config=config, region_name=REGION)
```

One entry per strategy, each a namespace _prefix_ for this actor: the summary entry stops before `/sessions/`, so it searches the summaries of all this actor's earlier sessions.
**Question:** Why is `MEMORY_RELEVANCE_SCORE` 0.3, and why do preferences use no threshold at all?
#### Answer
The original guide used 0.7. But the semantic-memory score for an exact stored fact is about 0.45, so a 0.7 threshold drops everything and nothing is ever recalled. 0.3 keeps relevant facts and summaries while still filtering noise. A preference is different: “answer in French” has nothing in common with “how many people work in Sales?”, so its relevance score is low, yet it applies to every answer. Preferences are few per user, so the agent always takes the top 5.
### Run your agent on your laptop
Your agent is deployed to AgentCore Runtime in Task 4, but you can already run it: `uv run bootcamp.py invoke "What do you know about me?" --actor alice-chen --local` starts `phase2/app/agent/agent.py` on your laptop (`localhost:8080`) and asks it as a signed-in user. It uses your real Memory, Gateway and model, so edit, invoke, repeat: no deploy. This is the everyday loop of agent work: iterate locally against real resources, deploy once it works.
The CLI starts the agent with the environment variables Terraform sets on the runtime (read from your stack's outputs) and your own AWS credentials, then plays the runtime's part: every request carries a workload access token for `awsworkshop-<you>-local`, the workload identity this stage creates, so `@requires_access_token` can fetch the Gateway token. Nothing checks the user's token locally (the runtime's JWT authorizer does that in Task 4), which is why the CLI always signs in as a real user.
The first run installs the agent's packages (about a minute); later runs start in seconds. The agent's output and errors go to `.build/local-agent/agent.log`. Until `up 4`, the Task 3 checks run your local agent the same way.
### Show Alice what the assistant knows
Challenge
Alice wants to see what the assistant knows about her. The reply already says who the agent believes it is talking to (`actor_id`, from the verified token). Make it also include `memories`: the long-term facts AgentCore Memory holds for that actor. You change `run_agent` in `phase2/app/agent/agent.py`. Expect an empty list right after someone states a fact: long-term extraction runs in the background and takes about 1-2 minutes.
**Where:** edit `phase2/app/agent/agent.py` in place, nothing to deploy; then check with `uv run bootcamp.py test --only 3` (the `[CHALLENGE]` line _memories in the reply_) and `uv run bootcamp.py invoke "What do you know about me?" --actor alice-chen --local`.
Docs
- AgentCore Memory: retrieve memory records (https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/long-term-retrieve-records.html)
- AgentCore Memory: memory organization (https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-organization.html)
#### Hint 1
The reply is the last thing `run_agent()` yields, and it already has `actor_id`. Facts live in the namespace `/strategies/{MEMORY_STRATEGY_ID}/actors/{actor_id}`.
#### Hint 2
`boto3.client("bedrock-agentcore").list_memory_records(memoryId=..., namespacePath=..., maxResults=20)` returns `memoryRecordSummaries[].content.text`. The runtime role already allows `ListMemoryRecords`. Return `[]` when there are none.
#### Solution: on the task page (open it only when the participant asks for the solution)
### Remember how Alice likes her answers
Challenge
Alice wants every answer in French, without repeating it each session. Tell the agent once, then prove a _new_ session follows it, and find the record that makes it happen.
**Where:** a terminal exercise, no file edits and no deploy. Talk to the agent with `invoke --local`, read the record with `uv run bootcamp.py memory --actor alice-chen`, and run `uv run bootcamp.py test --only 3` (_preference recalled_).
Docs
- AgentCore Memory: user preference strategy (https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/user-preference-memory-strategy.html)
- AgentCore Memory: retrieve memory records (https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/long-term-retrieve-records.html)
#### Hint 1
Which strategy should catch “I prefer ...”? Look at the table above, then at `long_term_retrieval`: which namespace does the agent search for it?
#### Hint 2
Extraction is asynchronous: wait 1-2 minutes, then list the records with `uv run bootcamp.py memory --actor <you>`. Ask your next question _without_ `--session last`, so only long-term memory can carry the preference.
#### Solution: on the task page (open it only when the participant asks for the solution)
### Experiments
- Run `uv run bootcamp.py memory --actor alice-chen` after a few invokes: compare the short-term sessions and events with the long-term records in each namespace. Which records appear after one turn, and which only after a longer session?
- Set `ALWAYS` to `MEMORY_RELEVANCE_SCORE` and ask a data question with `invoke --local`: is the French preference still followed?
- What would you trade by raising `top_k` to 20, or the relevance score to 0.7?
- Add an `EPISODIC` strategy: set `MEMORY_EPISODIC=true` in `.env` and run `uv run bootcamp.py deploy`. The platform adds an **Episodes** strategy (template `/strategies/{memoryStrategyId}/actors/{actorId}/sessions/{sessionId}`, see `terraform/participant/task3_memory.tf`). Have a short multi-turn session (`--session last`), then look at its records with `memory`. The agent does not retrieve them (`long_term_retrieval` has no entry for it): which namespace would you add? Extraction is shared quota in this account: keep it to a few turns, then set it back to `false` and `deploy`.
### Re-test
**See it in the console:** **AgentCore → Memory** (https://us-east-1.console.aws.amazon.com/bedrock-agentcore/memory?region=us-east-1): your memory, its three strategies and their namespaces; `uv run bootcamp.py memory` lists the records in them.
The challenge lines run your agent locally until `up 4` deploys it (the preference one takes 2-5 minutes, mostly waiting for extraction):

terminal:
```bash
uv run bootcamp.py test --only 3
```

expected [CHALLENGE] line:
```text
[CHALLENGE] SKIP stage 3 memories in the reply: the reply has no memories field yet
# after your change:
[CHALLENGE] PASS stage 3 memories in the reply: signed in as bootcamp-check-8560e352: actor_id=bootcamp-check-8560e352 memories=[]
```

This check depends on the model's wording, which varies from run to run. If it fails, rerun it once; check with `uv run bootcamp.py traces --args` which tool ran (the trace, not the wording, says whether the agent did the work); if the shipped agent does the same (`git stash`, `deploy`, rerun, `git stash pop`, `deploy`), it's the model, not your change.
**Lesson learned**
Memory isolation is only as good as the identity you pass in. The actor id is the partition key for every long-term fact, so **never trust caller-supplied identity**: take the actor from a verified token, and test with two different users (and one who lies about who they are).
## Check your work

terminal:
```bash
uv run bootcamp.py test --only 3
```

Passes when your memory is `ACTIVE` with the UserFacts, UserPreferences and SessionSummaries strategies, followed by two `[CHALLENGE]` lines that ask your agent (run locally until `up 4` deploys it).
#### Under the hood
**AgentCore Memory** stores conversation events per session and actor (short-term), and runs extraction strategies asynchronously to build long-term records. Each strategy uses a model to pull out its kind of record (facts, preferences, session summaries), consolidates it with what is already stored (a changed preference replaces the old one), and indexes it for vector retrieval. Strands' `AgentCoreMemorySessionManager` writes each turn as an event and injects retrieved facts into the context before the model call. Extraction takes a minute or so, so a fact isn't searchable instantly.
