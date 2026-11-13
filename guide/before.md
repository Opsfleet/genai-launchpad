Before the workshop
# Get ready for day 1
A few days ahead: open your browser workspace (nothing to install), or set up your laptop in about 20 minutes, then run one check. Whatever fails here would otherwise cost you the first hour of the workshop.
## Using a browser workspace?
If your invitation email has an _Open your browser workspace_ step, the tools, the repository and `.env` are already set up there and no access key is needed. Otherwise open _Running from your laptop_ below.
### Open your space
Sign in, switch to your workshop role, then search the console for **SageMaker AI** > **Studio** > **Open Studio** > **Code Editor**. Next to your space press **Run**, then **Open** (the first start takes a few minutes).
### Open the project folder
In Code Editor: menu **☰** (top left) > **File** > **Open Folder...**, choose `/home/sagemaker-user/datastream-bootcamp` and press **OK** (trust the authors when asked). Code Editor reopens it next time.
### Open a terminal and check
Menu **☰** > **Terminal** > **New Terminal** (or Ctrl+`). It opens in the project folder; run `uv run bootcamp.py doctor`. Every command on this site runs there.
### Optional: ask Claude Code
Type `claude` in the terminal for a coding assistant that already knows your gateway: it uses Haiku by default (`/model sonnet` for harder questions) and every call comes out of your LiteLLM budget, shown in its status line. `/clear` between unrelated questions keeps it cheap.
An idle space stops after an hour; your files stay. Press **Run** again to continue.
#### Running from your laptop
### Install the tools
uv (https://docs.astral.sh/uv/) (it installs Python 3.13 for you), Terraform (https://developer.hashicorp.com/terraform/install) 1.9 or later (Phase 2 drives it for you; you never edit it), the AWS CLI v2 (https://aws.amazon.com/cli/) and git.

terminal · macOS / Linux:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
brew tap hashicorp/tap
brew install hashicorp/tap/terraform awscli   # Terraform >= 1.9
uv --version && terraform -version && aws --version
```

terminal · Windows PowerShell:
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
winget install Hashicorp.Terraform Amazon.AWSCLI
uv --version; terraform -version; aws --version
```

### Clone and configure

terminal:
```bash
git clone https://github.com/Opsfleet/genai-launchpad.git datastream-bootcamp
cd datastream-bootcamp
uv sync
```

terminal · macOS / Linux:
```bash
cp .env.example .env
```

terminal · Windows PowerShell:
```powershell
Copy-Item .env.example .env
```

In `.env` set `PARTICIPANT` to the name your instructor gave you (it starts blank on purpose); `AWS_PROFILE=bootcamp`, the profile you create in the next step, is already set. `BOOTCAMP_VERBOSE=1` (or `--verbose` on any command) shows full terraform output and debug logs in Phase 2.

.env (copied from .env.example):
```bash
# Your bootcamp name: copy it from your invitation email (first+last name, lowercase letters/digits, e.g. janedoe). Required.
PARTICIPANT=
# The AWS profile holding your access key (`aws configure --profile bootcamp`). Blank = environment variables.
AWS_PROFILE=bootcamp
# Bootcamp region (wins over any AWS_REGION exported in your shell).
BOOTCAMP_REGION=us-east-1
# Optional: a model from `uv run bootcamp.py llm models`; empty = the class default.
MODEL_ID=
# Optional: override the role to assume (default bootcamp-participant-<PARTICIPANT>); "none" = use AWS_PROFILE as-is.
BOOTCAMP_ROLE_ARN=
# Optional agent capabilities (need stage >= 4; apply with `uv run bootcamp.py deploy`):
# run_python tool on the AWS-managed AgentCore Code Interpreter, browse_web tool on the AWS-managed AgentCore Browser.
ENABLE_CODE_INTERPRETER=false
ENABLE_BROWSER=false
# Bedrock Guardrail on every agent model call (prompt-attack filter, email/phone masking) + tool-output screening.
ENABLE_GUARDRAILS=false
# Guardrail experiments (with ENABLE_GUARDRAILS=true; apply with `deploy`): prompt-attack filter strength on user
# input (NONE, LOW, MEDIUM, HIGH) and the PII types masked in answers (comma list of Bedrock PII types, or none).
#GUARDRAIL_PROMPT_ATTACK_STRENGTH=MEDIUM
#GUARDRAIL_PII_TYPES=EMAIL,PHONE
# Memory experiment (stage >= 3; apply with `deploy`): add an EPISODIC strategy next to the three shipped ones.
#MEMORY_EPISODIC=false
# INSECURE identity experiment (stage >= 4; apply with `deploy`): the agent trusts a caller-set actor header again,
# so any signed-in user can read another user's memories. Task 4 only; set it back to false and deploy afterwards.
#TRUST_ACTOR_HEADER=false
# Optional: 1 = full terraform output and debug logs (same as --verbose).
BOOTCAMP_VERBOSE=0
```

### Sign in to AWS
Open the sign-in URL from your invitation email, sign in with the username and temporary password, and choose your own password. Then create a key for the command line: account menu (top right) > **Security credentials** > **Create access key** > _Command Line Interface (CLI)_. Copy both values (the secret is shown only once), save them as the `bootcamp` profile and check who you are:

terminal:
```bash
aws configure --profile bootcamp   # key, secret, region from the email, output json
aws sts get-caller-identity --profile bootcamp
```

It prints your user, `bootcamp-<name>`, which can do one thing: switch into your workshop role `bootcamp-participant-<name>`. The CLI switches for you and refreshes the credentials, so long sessions don't hit a one-hour limit. To look around in the console (your agents, logs, traces), use the **switch role** link from the email each time you sign in. Lost your password? Ask your instructor for a new invitation.
### Run the pre-flight check

terminal:
```bash
uv run bootcamp.py doctor
```

It creates nothing, costs a fraction of a cent (one tiny model call) and finishes in seconds. Every line should start with ✔; send the output to your instructor either way.

terminal · expected output:
```bash
Checking this laptop for the bootcamp (up to ~30 s; nothing is created)...
✔ Operating system: macOS 15.5 (arm64)
✔ Python: 3.13.13
✔ uv: uv 0.11.8
✔ Terraform: Terraform v1.15.0 (>= 1.9)
✔ AWS CLI: aws-cli/2.34.40
✔ Disk space: 163.7 GiB free
✔ AWS credentials: arn:aws:iam::123456789012:user/bootcamp/bootcamp-alice (from bootcamp)
✔ .env PARTICIPANT: alice (.env), region us-east-1
✔ Participant role: assumed bootcamp-participant-alice in us-east-1
✔ Gateway settings: https://llm.bootcamp.example.com
✔ LiteLLM call: gpt-6-luna answered in 1.0 s
✔ LiteLLM budget: $10.0000 left of $10
✔ Bedrock: direct Bedrock is denied, as designed (models go through LiteLLM)
✔ Network: Cognito: https://cognito-idp.us-east-1.amazonaws.com/ answered HTTP 400
✔ Network: National Weather Service: https://api.weather.gov/ answered HTTP 200
✔ Network: GitHub: https://github.com/ answered HTTP 200

16 pass. Ready for day 1.
```

## When a line fails
CheckUsually meansFix
Terraform, AWS CLI, uvNot installed or too oldInstall from the links above, open a new terminal
AWS credentialsYour access key is wrong or deleted, or `AWS_PROFILE` is wrong`aws configure --profile bootcamp` with a key from the console (Security credentials)
.env PARTICIPANTBlank or malformed nameSet the name your instructor gave you in `.env`
Participant roleYour name is not on the deployed roster, or the key belongs to another userCheck the spelling, then tell your instructor
Gateway settingsWrong region, or your key was not synced yetCheck `BOOTCAMP_REGION`, then tell your instructor
LiteLLM call / budgetGateway unreachable (HTTP 503 outside 08:00-22:00 Israel time, when it is off), or your budget is used upRetry within the gateway's hours; otherwise check VPN/proxy, then tell your instructor
Bedrock`WARN` only: direct Bedrock should be deniedTell your instructor (nothing to fix on your side)
NetworkA proxy or firewall blocks an HTTPS hostAsk IT to allow the hosts listed below
### Corporate networks
Behind a proxy or firewall, HTTPS must reach:
- Cognito: `https://cognito-idp.<region>.amazonaws.com/`
- National Weather Service: `https://api.weather.gov/`
- GitHub: `https://github.com/`
- AWS APIs (`*.amazonaws.com`), the bootcamp gateway and site your instructor shares
- Python packages and Terraform providers (`pypi.org`, `files.pythonhosted.org`, `registry.terraform.io`, `releases.hashicorp.com`)
Stuck? Run `uv run bootcamp.py doctor --verbose` and send the output to your instructor before the workshop.
## Getting updates during the class
When your instructor announces an update, pull it from the project folder. Stash your own edits first (a plain `git pull` refuses to overwrite files you changed) and bring them back after:

terminal:
```bash
git stash && git pull && git stash pop
```

If `stash pop` reports a conflict, keep your version of the file or ask your instructor.
