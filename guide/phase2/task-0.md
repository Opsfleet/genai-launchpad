Task 0 · 8 tasks
# Identity with Cognito
Two kinds of identity: a machine-to-machine token for your services, and signed-in users for people.
15 minEasy
Alice’s ask
## The “Enterprise Readiness” challenge
The local prototype won Alice over. Now she wants it in production for all 1,200 employees, and IT has one rule: nothing gets called without a verifiable identity.
In the original workshop this meant an hour of console clicking. Here the platform does it, and you spend the time understanding what a token actually carries.
Platform
## What the platform provisions for you

terminal:
```bash
uv run bootcamp.py up 0
```

- A Cognito user pool for you, with a resource server and the scope `datastream/mcp.access`
- An app client allowed to use the OAuth _client credentials_ (M2M) flow
- A Cognito domain that issues tokens (named `ds-<10 hex chars>-<account>`)
- A second, _user_ app client (username + password sign-in, no secret) and two DataStream users, `alice-chen` and `jordan-lee`, whose generated passwords are stored as SSM SecureString parameters under `/workshop/awsworkshop-<name>-users/`
- Nothing for model access: your laptop already reaches the LiteLLM gateway keylessly with your participant role
Adding this stage usually takes **~6 min**; the CLI prints progress (and full terraform output with `--verbose`).
Most of that time is a deliberate ~5 minute pause on the very first `up 0`: a new Cognito domain needs time for DNS to propagate. A heartbeat line every minute shows it is still working.
**While you wait**
Read `terraform/participant/task0_cognito.tf`: find the two app clients (machine and user) and the scope. Or open **Amazon Cognito → User pools** (https://us-east-1.console.aws.amazon.com/cognito/v2/idp/user-pools?region=us-east-1) in the console and watch yours appear.
You
## What you do as a developer
### Get a token

terminal:
```bash
uv run bootcamp.py token
```

That long string is a JWT. Every later stage (MCP runtime, Gateway, Agent) checks it.
### Peek inside
A JWT is three base64url parts (header, payload, signature); the claims are in the payload. Decode yours (`--claims` base64url-decodes that middle part; it does not check the signature):

terminal:
```bash
uv run bootcamp.py token --claims
```

`scope` is `datastream/mcp.access`, the scope your runtimes and Gateway require. `client_id` is your M2M app client, the only one their JWT authorizers allow. `exp` is when it expires.
Docs
- Amazon Cognito: understanding the access token (https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-the-access-token.html)
- AgentCore Identity: inbound JWT authorizer (https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/inbound-jwt-authorizer.html)
### Sign in as a user
Machines use the M2M token above. People sign in: the CLI reads Alice's password from SSM Parameter Store and calls Cognito `InitiateAuth`, exactly what a login page would do.

bootcamp_cli/users.py:
```python
def stored_password(session: boto3.Session, out: dict, username: str) -> str:
    """A story user's password from SSM Parameter Store (decrypted)."""
    name = f"{out['users_parameter_path']}/{username}"
    return session.client("ssm").get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]

def sign_in(session: boto3.Session, out: dict, username: str, password: str) -> str:
    """Sign in through the pool's user app client (no client secret) and return the user's access token."""
    response = session.client("cognito-idp").initiate_auth(
        ClientId=out["user_client_id"],
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": username, "PASSWORD": password},
    )
    return response["AuthenticationResult"]["AccessToken"]
```

terminal:
```bash
uv run bootcamp.py token --actor alice-chen
```

Decode it like the M2M token: this one has a `username` claim (`alice-chen`), the _user_ client's `client_id`, and no `datastream/mcp.access` scope. In Task 4 your agent accepts only this kind of token, and reads who is talking from `username`.
### See your ids

terminal:
```bash
uv run bootcamp.py status
```

Prints `POOL_ID` and friends. Later stages add more lines here.
**See it in the console:** **Amazon Cognito → User pools → your pool** (https://us-east-1.console.aws.amazon.com/cognito/v2/idp/user-pools?region=us-east-1): **Users** lists `alice-chen` and `jordan-lee`; **App clients** the machine and the user client.
## Check your work

terminal:
```bash
uv run bootcamp.py test --only 0
```

Four checks pass: Cognito issues a token for your client, both story users sign in with their stored passwords, _litellm keyless identity_ (the gateway recognises your role) and _no direct bedrock_ (a direct Bedrock call is refused with `AccessDenied`, as intended).
#### Under the hood
**Amazon Cognito** is AWS's identity provider. For service-to-service calls it uses the OAuth 2.0 client-credentials grant: your app client trades its id and secret for a short-lived access token scoped to `datastream/mcp.access`. AgentCore resources are configured with a _JWT authorizer_ pointing at the pool's OIDC discovery URL, so they validate signatures and scopes without ever calling Cognito per request.
For people, the pool holds _users_. Signing in (`InitiateAuth` with `USER_PASSWORD_AUTH`) returns an access token whose `username` claim names the user, signed by the pool. A service that trusts that claim, and nothing the caller can simply type, knows who it is serving.
You work as the role `bootcamp-participant-<name>`, which the CLI assumes for you (`BOOTCAMP_ROLE_ARN` only overrides it). That role can only touch resources tagged `Participant=<name>` or named `awsworkshop-<name>-*`, and every role you create carries a permissions boundary that blocks direct Bedrock calls: LiteLLM is the only path to a model.
