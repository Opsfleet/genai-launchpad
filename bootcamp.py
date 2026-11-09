"""DataStream Corp bootcamp CLI. Works the same on macOS, Linux and Windows.

Participants (run as your tag-isolated bootcamp-participant-<name> role; every model call goes through LiteLLM):
    uv run bootcamp.py phase1 t2 "..." run a Phase 1 task script (no prompt = interactive chat)
    uv run bootcamp.py phase1 t3 --session bob   t3/t4: chat in a named session (a new name starts fresh)
    uv run bootcamp.py doctor          pre-flight check of this laptop before day 1 (tools, AWS, gateway, network)
    uv run bootcamp.py llm             gateway URL, models and your remaining budget
    uv run bootcamp.py llm models      the models you may use, with their price per million tokens
    uv run bootcamp.py llm budget      your spend, limit and what is left
    uv run bootcamp.py up 4            provision Phase 2 tasks 0..4 (lower N switches tasks off)
    uv run bootcamp.py deploy          redeploy your edited agent / MCP server code at the current stage
    uv run bootcamp.py test [N]        smoke-test every stage up to N (default: current stage)
    uv run bootcamp.py status          print your resource ids
    uv run bootcamp.py invoke "..."    talk to your deployed agent as a signed-in user (--actor jordan-lee; --stream
                                       prints the answer as it is generated; --session last; --json raw; --local
                                       runs your agent.py on this machine instead, no deploy needed)
    uv run bootcamp.py traces [ID]     span tree of your latest invoke (or the given session; --args tool inputs)
    uv run bootcamp.py scores          your agent's recent online-evaluation scores
    uv run bootcamp.py memory          what AgentCore Memory holds for an actor (--actor; short- and long-term)
    uv run bootcamp.py eval            offline evaluation: golden questions with ground truth (--last: saved run)
    uv run bootcamp.py eval --evaluators all --variants A,B   + your custom evaluators; A/B of two prompt variants
    uv run bootcamp.py token           print a Cognito M2M access token (MCP server, Gateway); --actor X: a user's
    uv run bootcamp.py tools           your Gateway's tools per target; prompt tokens: every tool vs semantic search
                                       (--sql "...": one query_db call straight through the Gateway, no model)
    uv run bootcamp.py down            destroy everything you provisioned
    uv run bootcamp.py forget          drop your local terraform state after the instructor reset your stack

The account stack (LiteLLM gateway, roles, site) belongs to the instructor and is driven by instructor.py.

Add --verbose anywhere (or BOOTCAMP_VERBOSE=1) for full terraform output and debug logging.
"""

import argparse
import logging
import re
import subprocess
import sys
from functools import partial
from pathlib import Path

import httpx
from botocore.exceptions import ClientError

from bootcamp_cli import (
    ab_compare,
    agentcore,
    checks,
    cli,
    datasets,
    doctor,
    evaluate,
    evaluators,
    forget,
    golden,
    invoke,
    llm_info,
    local_agent,
    memory,
    observe,
    progress,
    tf,
    tool_search,
    users,
)
from bootcamp_cli.build import build_app, seed_database
from bootcamp_cli.cli import approve_flags, global_options
from bootcamp_cli.config import ROOT
from bootcamp_cli.errors import raise_if_gateway_down
from bootcamp_cli.gateway_key import read_gateway
from bootcamp_cli.stack import PARTICIPANT_DIR, participant_vars

sys.path.insert(0, str(ROOT / "shared"))

import litellm_gateway  # noqa: E402

log = logging.getLogger("bootcamp")
HIDDEN_OUTPUTS = {"client_secret"}
PARTICIPANT_LOG_PREFIXES = (
    "/aws/bedrock-agentcore/runtimes/awsworkshop_{participant}_",
    "/aws/bedrock-agentcore/evaluations/results/awsworkshop_{participant}_",
)


class Context(cli.Context):
    """The participant's settings and role session, plus their stack outputs and gateway settings."""

    def __init__(self) -> None:
        super().__init__(as_participant=True)

    def participant_outputs(self) -> dict:
        tf.prepare(PARTICIPANT_DIR, self.env, self.settings.participant)
        return tf.outputs(PARTICIPANT_DIR, self.env)

    def gateway(self) -> dict:
        """The participant's LiteLLM settings, with a clear message when the key secret is missing or denied."""
        try:
            return read_gateway(self.session, self.settings.participant)
        except ClientError as error:
            raise RuntimeError(self._gateway_problem(error)) from error

    def model_id(self) -> str:
        """MODEL_ID from .env, else the class default your instructor chose (`llm models` marks it)."""
        return self.settings.model_id or self.gateway().get("default_model", "")

    def runtime_model_id(self) -> str:
        """The model's Bedrock ID for the deployed agent, so Observability can price its traces (gateway alias)."""
        return self.gateway().get("bedrock_ids", {}).get(self.model_id(), self.model_id())

    def _gateway_problem(self, error: ClientError) -> str:
        code = error.response.get("Error", {}).get("Code", "")
        where = f"participant '{self.settings.participant}' in region {self.settings.region}"
        if code == "ResourceNotFoundException":
            return f"No LiteLLM key for {where}: ask the instructor to add you to roster.json (or fix BOOTCAMP_REGION)."
        if code in {"AccessDeniedException", "AccessDenied"}:
            return f"Not allowed to read the LiteLLM key for {where}: check PARTICIPANT in .env."
        return f"Reading the LiteLLM key for {where} failed: {error}"


def apply_stage(ctx: Context, args: argparse.Namespace, stage: int) -> dict:
    if stage >= 1:
        seed_database()
        build_app("mcp_server")
    if stage >= 2:
        build_app("weather_lambda")
    if stage >= 4:
        build_app("agent")
    if stage >= 6:
        build_app("code_evaluator")
        build_app("rubric_judge")
    tf.prepare(PARTICIPANT_DIR, ctx.env, ctx.settings.participant)
    variables = participant_vars(ctx.settings, stage, ctx.gateway()["base_url"], ctx.runtime_model_id())
    tf.run_live(PARTICIPANT_DIR, ["apply", "-input=false", *variables, *approve_flags(args)], ctx.env, ctx.verbose)
    return tf.outputs(PARTICIPANT_DIR, ctx.env)


def check_outputs(ctx: Context, out: dict) -> dict:
    """Terraform outputs plus the gateway URL and model the checks (and a local agent) need."""
    return out | {"litellm_base_url": ctx.gateway()["base_url"], "model_id": ctx.model_id()}


def run_checks(ctx: Context, out: dict, stage: int, only: int | None) -> bool:
    """Stage smoke checks, with a heartbeat through their long waits (Cognito DNS, memory extraction)."""
    with progress.heartbeat("running stage checks"):
        return checks.run_checks(out, ctx.session, stage, only=only)


def cmd_up(ctx: Context, args: argparse.Namespace) -> int:
    current = int(ctx.participant_outputs().get("stage", -1))
    what = f"Provisioning stage {args.stage}" if current < args.stage else f"Re-applying stage {args.stage}"
    progress.announce(what, progress.up_minutes(current, args.stage))
    out = check_outputs(ctx, apply_stage(ctx, args, args.stage))
    return 0 if args.skip_test or run_checks(ctx, out, args.stage, args.stage) else 1


def cmd_deploy(ctx: Context, args: argparse.Namespace) -> int:
    stage = int(ctx.participant_outputs().get("stage", 0))
    if stage < 1:
        raise RuntimeError("Nothing to deploy yet: run `up 1` (MCP server) or `up 4` (agent) first.")
    progress.announce(f"Redeploying your code at stage {stage}", progress.EXPECTED_MINUTES["deploy"])
    log.info("  (can take up to ~10 min when the runtime is still updating from a previous change)")
    apply_stage(ctx, args, stage)
    log.info("Redeployed your code at stage %s", stage)
    return 0


def cmd_test(ctx: Context, args: argparse.Namespace) -> int:
    out = check_outputs(ctx, ctx.participant_outputs())
    stage = int(out.get("stage", 0)) if args.stage is None else args.stage
    return 0 if run_checks(ctx, out, stage, args.only) else 1


def cmd_status(ctx: Context, _: argparse.Namespace) -> int:
    out = ctx.participant_outputs()
    if not out:
        print(f"No stack provisioned for '{ctx.settings.participant}' (start with `uv run bootcamp.py up 0`).")
        return 0
    for key, value in out.items():
        if key not in HIDDEN_OUTPUTS and value != "":
            print(f"{key.upper()}={value}")
    return 0


def gateway_client(ctx: Context) -> httpx.Client:
    """An httpx client on your LiteLLM gateway, signed with your AWS identity (no API key)."""
    auth = litellm_gateway.StsIdentityAuth(ctx.session)
    gateway = ctx.gateway()
    hooks = {"response": [partial(raise_if_gateway_down, gateway.get("active_hours"))]}
    return httpx.Client(base_url=gateway["base_url"], auth=auth, timeout=30, event_hooks=hooks)


def key_info(client: httpx.Client) -> dict:
    """Your LiteLLM key's spend and budget."""
    return client.get("/key/info").raise_for_status().json().get("info", {})


def cmd_llm(ctx: Context, args: argparse.Namespace) -> int:
    with gateway_client(ctx) as client:
        info = key_info(client)
        if args.view == "models":
            rows = client.get("/model/info").raise_for_status().json()["data"]
            print("\n".join(llm_info.render_models(rows, info, ctx.model_id())))
            return 0
        if args.view == "budget":
            print("\n".join(llm_info.render_budget(info)))
            return 0
        models = [m["id"] for m in client.get("/v1/models").raise_for_status().json()["data"]]
    print(f"LITELLM_BASE_URL={client.base_url}\nMODELS={', '.join(models)}\nMODEL_ID={ctx.model_id()}")
    limit = info.get("max_budget")
    print(f"BUDGET=${info.get('spend', 0):.6f} spent of " + ("no limit" if limit is None else f"${limit:g}"))
    return 0


def current_spend(ctx: Context) -> float:
    """Your LiteLLM spend so far in USD."""
    with gateway_client(ctx) as client:
        return float(key_info(client).get("spend") or 0.0)


def cmd_eval(ctx: Context, args: argparse.Namespace) -> int:
    participant = ctx.settings.participant
    if args.last:
        report = evaluate.load_last(participant)
    else:
        report = _run_eval(ctx, args)
        evaluate.save(participant, report)
    rendered = ab_compare.render(report) if len(report.variants) > 1 else evaluate.render(report)
    print("\n".join([*rendered, *evaluate.failures(report)]))
    rate = ab_compare.lowest_pass_rate(report) if report.variants else evaluate.pass_rate(report.results)
    return 0 if rate >= args.min_pass else 1


def _run_eval(ctx: Context, args: argparse.Namespace) -> evaluate.Report:
    """Sync the golden file to your managed dataset, then ask and batch-evaluate its first --limit items."""
    out, items = ctx.participant_outputs(), golden.load_items(args.dataset)
    options = evaluate.RunOptions(args.limit, args.evaluators, tuple(args.variants))
    evaluate.check_size(len(items), options)
    version = datasets.sync(ctx.session.client("bedrock-agentcore-control"), ctx.settings.participant, items)
    log.info("Dataset %s version %s (%d items%s)", version.name, version.version, len(version.items),
             ", new version" if version.changed else "")  # fmt: skip
    spend_before = current_spend(ctx)
    report = evaluate.run(ctx.session, out, ctx.settings.participant, version, options)
    report.spend_usd = current_spend(ctx) - spend_before
    return report


def cmd_token(ctx: Context, args: argparse.Namespace) -> int:
    out = ctx.participant_outputs()
    print(users.user_token(ctx.session, out, args.actor) if args.actor else agentcore.get_token(out))
    return 0


def cmd_tools(ctx: Context, args: argparse.Namespace) -> int:
    out = ctx.participant_outputs()
    if not out.get("gateway_url"):
        raise RuntimeError("No Gateway yet: run `uv run bootcamp.py up 2` first.")
    gateway = (out["gateway_url"], agentcore.get_token(out))
    if args.sql:
        print(tool_search.query_through_gateway(gateway, args.sql))
        return 0
    every, found = tool_search.discover(gateway, args.search, args.top_k)
    listing = tool_search.listing_lines(tool_search.names(every), tool_search.names(found), args.search)
    print("\n".join(listing), flush=True)
    print("\n".join(_token_report(ctx, every, found)))
    return 0


def _token_report(ctx: Context, every: list[dict], found: list[dict]) -> list[str]:
    """Prompt tokens per tool list on your model, or one warning line when the model call fails."""
    model = ctx.model_id()
    try:
        with gateway_client(ctx) as client:
            return tool_search.token_lines(tool_search.measure(client, model, every, found), model)
    except Exception as error:  # noqa: BLE001 - the listing already printed; the measurement is a bonus
        return [tool_search.token_warning(model, error)]


def cmd_invoke(ctx: Context, args: argparse.Namespace) -> int:
    out = ctx.participant_outputs()
    if not args.local:
        if not out.get("agent_runtime_arn"):
            raise RuntimeError("No agent deployed yet: run `up 4`, or try your agent.py first with `invoke --local`.")
        return _invoke(ctx, args, out)
    out = check_outputs(ctx, out)
    with local_agent.running(out, out["model_id"], ctx.session) as local:
        return _invoke(ctx, args, out | local)


def _invoke(ctx: Context, args: argparse.Namespace, out: dict) -> int:
    """Ask the agent `out` points at (deployed, or local with `local_agent_url`) as a signed-in user."""
    participant, where = ctx.settings.participant, "local agent" if args.local else "agent"
    session_id = invoke.resolve_session(args.session, participant)
    token = users.user_token(ctx.session, out, args.actor)
    log.info("Asking your %s as %s (usually 10-40 s, a few more on a cold start)...", where, args.actor)
    invoke.remember(participant, session_id, args.actor, args.prompt)
    ask = _stream_reply if args.stream else _json_reply
    reply, tools = ask(out, token, args, session_id)
    actor = reply.get("actor_id", args.actor)
    spans = f"agent log: {local_agent.LOG_FILE.relative_to(ROOT)}" if args.local else "spans: `traces`"
    print(f"({tools}session: {session_id}, actor: {actor}; same session: --session last; {spans})", file=sys.stderr)
    return 0


def _json_reply(out: dict, token: str, args: argparse.Namespace, session_id: str) -> tuple[dict, str]:
    """One JSON reply, printed when complete; returns it with an empty tools note."""
    reply = invoke.with_deadline(lambda: agentcore.invoke_agent_body(out, token, args.prompt, session_id), session_id)
    print(invoke.render_reply(reply, args.json), flush=True)
    return reply, ""


def _stream_reply(out: dict, token: str, args: argparse.Namespace, session_id: str) -> tuple[dict, str]:
    """The answer printed as it is generated; returns the final reply and a note of the tools it called."""
    events = agentcore.stream_agent(out, token, args.prompt, session_id)
    printer = invoke.with_deadline(lambda: invoke.print_stream(events, args.json), session_id)
    return printer.reply, f"tools: {', '.join(printer.tools) or 'none'}; "


def cmd_traces(ctx: Context, args: argparse.Namespace) -> int:
    logs, service = ctx.session.client("logs"), observe.service_name(ctx.settings.participant)
    session_id = args.session or _default_trace_session(ctx, logs, service, args.hours)
    spans = observe.session_spans(logs, service, session_id, args.hours) if session_id else []
    if not spans:
        print(_no_spans_message(service, session_id, args.hours))
        return 0
    inputs = observe.tool_inputs(logs, _runtime_log_group(ctx), session_id, args.hours) if args.args else {}
    print(f"session {session_id} ({len(spans)} spans)")
    print("\n".join(observe.render_tree(spans, inputs)))
    if args.args and not inputs:
        print(observe.NO_TOOL_INPUTS_HINT)
    return 0


def _default_trace_session(ctx: Context, logs, service: str, hours: float) -> str | None:
    """Your latest `invoke` on this machine, else the latest non-check session that produced spans."""
    return invoke.last_session(ctx.settings.participant) or observe.latest_session(logs, service, hours)


def _no_spans_message(service: str, session_id: str | None, hours: float) -> str:
    where = f"session {session_id}" if session_id else f"{service} in the last {hours:g}h"
    return f"No spans yet for {where} (they arrive 2-10 min after an invoke; stage 5+)."


def _runtime_log_group(ctx: Context) -> str | None:
    """The agent runtime's log group from terraform outputs (None before stage 4)."""
    return ctx.participant_outputs().get("agent_log_group") or None


def cmd_scores(ctx: Context, args: argparse.Namespace) -> int:
    rows = observe.recent_scores(ctx.session.client("logs"), ctx.settings.participant, args.hours, args.limit)
    if not rows:
        print(f"No evaluation results in the last {args.hours:g}h (stage 6+; results lag an invoke by up to ~25 min).")
        return 0
    print("\n".join(observe.render_scores(rows, _score_actors(ctx, rows, args.hours))))
    return 0


def _score_actors(ctx: Context, rows: list[dict[str, str]], hours: float) -> dict[str, str]:
    """Session -> actor from your local invoke history, else the first words of the session's prompt."""
    actors = invoke.session_actors(ctx.settings.participant)
    unknown = {row.get("session", "") for row in rows} - actors.keys()
    unknown = sorted(s for s in unknown if s and not agentcore.is_check_session(s))
    if not unknown:
        return actors
    prompts = observe.first_prompts(ctx.session.client("logs"), _runtime_log_group(ctx), unknown, hours)
    return actors | {session: f'"{prompt}"' for session, prompt in prompts.items()}


def cmd_memory(ctx: Context, args: argparse.Namespace) -> int:
    memory_id = ctx.participant_outputs().get("memory_id")
    if not memory_id:
        print("No memory yet: it is created at stage 3 (`uv run bootcamp.py up 3`).")
        return 0
    print("\n".join(memory.report(ctx.session, memory_id, args.actor)))
    return 0


def cmd_down(ctx: Context, args: argparse.Namespace) -> int:
    tf.prepare(PARTICIPANT_DIR, ctx.env, ctx.settings.participant)
    progress.announce("Destroying your stack", progress.EXPECTED_MINUTES["down"])
    destroy_args = ["destroy", "-input=false", *participant_vars(ctx.settings, 0), *approve_flags(args)]
    tf.run_live(PARTICIPANT_DIR, destroy_args, ctx.env, ctx.verbose)
    _delete_evaluation_resources(ctx)
    _delete_runtime_log_groups(ctx)
    return 0


def _delete_evaluation_resources(ctx: Context) -> None:
    """`eval` creates your dataset and batch evaluation jobs with boto3, so terraform does not track them."""
    evaluate.delete_batches(ctx.session.client("bedrock-agentcore"), ctx.settings.participant)
    datasets.delete_all(ctx.session.client("bedrock-agentcore-control"), ctx.settings.participant)


def _delete_runtime_log_groups(ctx: Context) -> None:
    """AgentCore creates runtime and evaluation-result log groups itself, so terraform does not track them."""
    logs = ctx.session.client("logs")
    for template in PARTICIPANT_LOG_PREFIXES:
        prefix = template.format(participant=ctx.settings.participant)
        for page in logs.get_paginator("describe_log_groups").paginate(logGroupNamePrefix=prefix):
            for group in page["logGroups"]:
                logs.delete_log_group(logGroupName=group["logGroupName"])
                log.info("Deleted %s", group["logGroupName"])


def cmd_forget(ctx: Context, args: argparse.Namespace) -> int:
    forget.forget(ctx, args.force)
    return 0


SESSION_TASKS = ("t3", "t4")
"""Phase 1 tasks with a FileSessionManager, where `--session NAME` applies."""


def cmd_phase1(ctx: Context, args: argparse.Namespace) -> int:
    folder = ROOT / "phase1" / ("starter" if args.starter else "")
    scripts = sorted(folder.glob(f"{args.task}_*.py"))
    if not scripts:
        raise SystemExit(f"No Phase 1 script for task '{args.task}' in {folder.relative_to(ROOT)} (expected t0..t8).")
    env = ctx.env | {"LITELLM_BASE_URL": ctx.gateway()["base_url"], "MODEL_ID": ctx.model_id()}
    if args.session and args.task not in SESSION_TASKS:
        raise SystemExit(
            f"--session works with {' and '.join(SESSION_TASKS)}, the tasks that save a session; {args.task} starts "
            "fresh every run (no prompt = an interactive chat that keeps context until you quit)."
        )
    if args.session:
        env["PHASE1_SESSION"] = args.session
    return subprocess.run([sys.executable, str(scripts[0]), *args.prompt], env=env, cwd=ROOT).returncode


def add_participant_commands(sub, common: argparse.ArgumentParser) -> None:
    """up/test/invoke/traces/scores and the argument-less participant commands."""
    up = sub.add_parser("up", parents=[common])
    up.add_argument("stage", type=int, choices=range(8))
    up.add_argument("--skip-test", action="store_true")
    test = sub.add_parser("test", parents=[common])
    test.add_argument("stage", type=int, nargs="?", choices=range(8))
    test.add_argument("--only", type=int, choices=range(8))
    add_invoke(sub, common)
    tools = sub.add_parser("tools", parents=[common], help="Gateway tools; prompt tokens, every tool vs search")
    tools.add_argument("--search", default=tool_search.DEFAULT_QUERY, help="what to ask the Gateway's tool search")
    tools.add_argument("--top-k", type=int, default=tool_search.DEFAULT_TOP_K, help="search results to keep")
    tools.add_argument("--sql", help="instead: send this SQL to query_db through the Gateway directly (no model)")
    add_observe_commands(sub, common)
    for name in ("status", "down", "deploy"):
        sub.add_parser(name, parents=[common])
    llm = sub.add_parser("llm", parents=[common], help="your gateway: summary, `llm models` or `llm budget`")
    llm.add_argument(
        "view",
        nargs="?",
        choices=["models", "budget"],
        help="models: what you may use, price per 1M tokens; budget: spent, limit, left; none: connection summary",
    )
    forget_parser = sub.add_parser("forget", parents=[common], help="drop your local state after an instructor reset")
    forget_parser.add_argument("--force", action="store_true", help="delete the workspace even if resources remain")


def add_invoke(sub, common: argparse.ArgumentParser) -> None:
    invoke_parser = sub.add_parser("invoke", parents=[common], help="ask your agent (--local: on this machine)")
    invoke_parser.add_argument("prompt")
    invoke_parser.add_argument(
        "--actor", default="alice-chen", help="sign in as alice-chen, jordan-lee or any other name (a test user)"
    )
    invoke_parser.add_argument("--stream", action="store_true", help="print the answer as it is generated")
    invoke_parser.add_argument(
        "--session", help="`last` reuses your previous invoke's (warm) session; or an id of 33+ characters"
    )
    invoke_parser.add_argument("--json", action="store_true", help="print the agent's raw JSON reply")
    invoke_parser.add_argument(
        "--local", action="store_true", help="run phase2/app/agent/agent.py on this machine (no deploy; stage 3+)"
    )
    token = sub.add_parser("token", parents=[common], help="print a Cognito access token (default: M2M)")
    token.add_argument("--actor", help="print this user's access token instead (signs in like `invoke --actor`)")


def add_observe_commands(sub, common: argparse.ArgumentParser) -> None:
    traces = sub.add_parser("traces", parents=[common], help="span tree of your latest (or the given) agent session")
    traces.add_argument("session", nargs="?", help="runtime session id (default: your latest `invoke`)")
    traces.add_argument("--hours", type=float, default=24, help="how far back to look")
    traces.add_argument("--args", action="store_true", help=observe.ARGS_HELP)
    scores = sub.add_parser("scores", parents=[common], help="your agent's recent online-evaluation results")
    scores.add_argument("--hours", type=float, default=24, help="how far back to look")
    scores.add_argument("--limit", type=int, default=20)
    add_eval(sub, common)
    memory_parser = sub.add_parser("memory", parents=[common], help="short- and long-term memory of one actor")
    memory_parser.add_argument("--actor", default="alice-chen")


EVALUATORS_HELP = "builtin (default), custom (your stage-6 evaluators), all, or comma-separated names/ids"
VARIANTS_HELP = "A/B: ask every item once per prompt variant (e.g. A,B) and compare them side by side"


def add_eval(sub, common: argparse.ArgumentParser) -> None:
    run = sub.add_parser("eval", parents=[common], help="offline evaluation: golden questions with ground truth")
    run.add_argument("--dataset", type=Path, default=golden.DEFAULT_PATH, help="golden file (.yaml or .csv)")
    run.add_argument(
        "--limit",
        type=int,
        default=evaluate.DEFAULT_LIMIT,
        help=f"ask at most this many items (max {evaluate.MAX_QUESTIONS} answers per run)",
    )
    run.add_argument("--min-pass", type=float, default=evaluate.MIN_PASS_RATE, help="exit 1 below this pass rate")
    run.add_argument("--last", action="store_true", help="print your latest saved run instead of running")
    run.add_argument("--evaluators", default=evaluators.DEFAULT_SPEC, help=EVALUATORS_HELP)
    run.add_argument("--variants", type=variant_list, default=[], help=VARIANTS_HELP)


def variant_list(value: str) -> list[str]:
    """`--variants A,B` -> ["A", "B"] (prompt variant names, upper-cased, no duplicates)."""
    return list(dict.fromkeys(part.strip().upper() for part in value.split(",") if part.strip()))


def add_phase1(sub, common: argparse.ArgumentParser) -> None:
    phase1 = sub.add_parser("phase1", parents=[common])
    phase1.add_argument("task", choices=[f"t{i}" for i in range(9)])
    phase1.add_argument("prompt", nargs="*")
    phase1.add_argument(
        "--starter", action="store_true", help="run your challenge file in phase1/starter/ instead of the reference"
    )
    phase1.add_argument(
        "--session", type=session_name, help="t3/t4: save the chat under this session id (a new name starts fresh)"
    )


def session_name(value: str) -> str:
    """`--session` value: letters, digits, `_` and `-` only (it becomes a folder under phase1/sessions/)."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise argparse.ArgumentTypeError("use 1-64 letters, digits, _ or -")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, parents=[global_options(False)]
    )
    sub = parser.add_subparsers(dest="command", required=True)
    common = global_options(True)
    add_participant_commands(sub, common)
    add_phase1(sub, common)
    sub.add_parser("doctor", parents=[common], help="pre-flight check of this laptop before day 1 (creates nothing)")
    return parser


COMMANDS = {
    "up": cmd_up,
    "deploy": cmd_deploy,
    "test": cmd_test,
    "status": cmd_status,
    "llm": cmd_llm,
    "token": cmd_token,
    "tools": cmd_tools,
    "invoke": cmd_invoke,
    "traces": cmd_traces,
    "scores": cmd_scores,
    "memory": cmd_memory,
    "eval": cmd_eval,
    "down": cmd_down,
    "forget": cmd_forget,
    "phase1": cmd_phase1,
}


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "doctor":
        return cli.run(args, doctor.run)
    return cli.run(args, lambda: COMMANDS[args.command](Context(), args))


if __name__ == "__main__":
    sys.exit(main())
