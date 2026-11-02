"""`bootcamp.py forget`: drop your local terraform workspace after the instructor reset your stack.

`instructor.py reset <you> --force` deletes your AWS resources but cannot touch the terraform state on your laptop,
which still lists them. `forget` refreshes that state against AWS (terraform drops resources that no longer exist),
and deletes the workspace only when nothing is left in it; `--force` deletes it regardless (only do that when the
instructor confirmed your stack is gone, or the resources it lists will be orphaned in the account).
"""

import logging

from bootcamp_cli import tf
from bootcamp_cli.cli import Context
from bootcamp_cli.stack import PARTICIPANT_DIR, participant_vars

log = logging.getLogger(__name__)

SHOWN_ADDRESSES = 10
LOCAL_ONLY_TYPES = ("terraform_data", "random_password")
"""Resource types with no object in AWS: a refresh never drops them, so they never block `forget`."""


def refreshed_addresses(ctx: Context) -> list[str]:
    """Resources still in your state after a refresh-only apply (which drops the ones deleted in AWS).

    The refresh runs at stage 0, like `down`: at the deployed stage, outputs such as `gateway_id` index resources
    the refresh just dropped (`this[0]` of an empty tuple) and fail the whole apply. A refresh-only apply never
    creates or destroys anything, so the stage only decides which outputs are evaluated.
    """
    env = dict(ctx.env)
    tf.prepare(PARTICIPANT_DIR, env, ctx.settings.participant)
    if not tf.state_addresses(PARTICIPANT_DIR, env):
        return []
    refresh = ["apply", "-refresh-only", "-input=false", "-auto-approve", *participant_vars(ctx.settings, 0)]
    tf.run_live(PARTICIPANT_DIR, refresh, env, ctx.verbose)
    return remote_addresses(tf.state_addresses(PARTICIPANT_DIR, env))


def remote_addresses(addresses: list[str]) -> list[str]:
    """The addresses backed by a real AWS object (drops `terraform_data.*` and other local-only types)."""
    return [address for address in addresses if address.split(".")[0] not in LOCAL_ONLY_TYPES]


def still_deployed(addresses: list[str]) -> str:
    """Why `forget` refuses while resources remain."""
    shown = "\n".join(f"  {address}" for address in addresses[:SHOWN_ADDRESSES])
    more = f"\n  ... and {len(addresses) - SHOWN_ADDRESSES} more" if len(addresses) > SHOWN_ADDRESSES else ""
    return (
        f"{len(addresses)} resources of yours still exist in AWS:\n{shown}{more}\n"
        "Run `uv run bootcamp.py down` to delete them, or ask the instructor to run "
        "`uv run instructor.py reset <you> --force`, then rerun `forget`. Right after a reset, wait a few "
        "minutes and rerun: AWS deletes some resources asynchronously (a memory takes about 5 minutes)."
    )


def forget(ctx: Context, force: bool) -> None:
    """Delete your local workspace once no AWS resource is left in its state (or unconditionally with `force`).

    The delete itself always passes `-force`: by then only local-only entries (`LOCAL_ONLY_TYPES`) can remain, and
    terraform refuses to delete a workspace whose state still lists anything. It first selects `default`:
    `prepare` creates workspaces with `workspace new`, which also makes them the checkout's active workspace, and
    terraform refuses to delete the active one (on a participant's laptop that is always their own).

    Raises:
        RuntimeError: Resources are still deployed and `force` was not given.
    """
    participant, env = ctx.settings.participant, dict(ctx.env)
    tf.prepare(PARTICIPANT_DIR, env, None)
    if participant not in tf.workspaces(PARTICIPANT_DIR, env):
        print(f"No local terraform workspace for '{participant}': nothing to forget.")
        return
    remaining = [] if force else refreshed_addresses(ctx)
    if remaining:
        raise RuntimeError(still_deployed(remaining))
    tf.terraform(PARTICIPANT_DIR, ["workspace", "select", "-no-color", "default"], env, capture=True)
    tf.terraform(PARTICIPANT_DIR, ["workspace", "delete", "-no-color", "-force", participant], env, capture=True)
    print(f"Forgot the local terraform state of '{participant}'. Start again with `uv run bootcamp.py up <stage>`.")
