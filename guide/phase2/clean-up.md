Finish
# Clean up
Remove everything you provisioned, and confirm nothing is left running on your name.
10 minEasy
Alice’s ask
## The “Leave No Trace” finish
Alice's assistant is live, observable and governed. Before you leave, tear your stack down: idle runtimes, gateways and memories still exist until you remove them.
You
## What you do as a developer
### Tear down your stack

terminal:
```bash
uv run bootcamp.py down
```

Usually takes **~10.5 min**. It destroys every stage you provisioned (agent, evaluators, Gateway with its weather Lambda and Cedar policy, Memory, MCP runtime, Cognito and the story users, your code bucket and its database copy, and the optional guardrail), then deletes what terraform does not track: your golden dataset and batch evaluations (created by `eval`) and your runtime and evaluation-result log groups.
### Verify

terminal:
```bash
uv run bootcamp.py status
```

expected output:
```text
No stack provisioned for '<you>' (start with `uv run bootcamp.py up 0`).
```

### What stays
Your participant role `bootcamp-participant-<you>`, your LiteLLM key and budget, and the secret `bootcamp/participants/<you>/litellm` belong to the instructor's account stack: you can't delete them and don't need to. Your local files (`phase1/datastream_corp.db`, `phase1/sessions/`, `.env`) stay on your laptop.
## Check your work
`status` prints _No stack provisioned_. If `down` stopped with an error, run it again: it picks up where it left off. If your instructor removed your stack for you (`instructor.py reset`), run `uv run bootcamp.py forget` instead to drop your stale local terraform state.
#### Under the hood
`down` runs `terraform destroy` on your participant workspace, then deletes the log groups AgentCore created for your runtimes and evaluations (`/aws/bedrock-agentcore/runtimes/awsworkshop_<you>_*` and `/aws/bedrock-agentcore/evaluations/results/awsworkshop_<you>_*`). After the workshop the instructor checks for leftovers with `instructor.py purge` before removing the account stack.
