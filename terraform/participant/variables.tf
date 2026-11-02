variable "participant" {
  description = "Participant id; prefixes every resource so many participants can share one account."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9]{0,15}$", var.participant))
    error_message = "participant must be 1-16 chars, lowercase letters/digits, starting with a letter."
  }
}

variable "stage" {
  description = "Highest Phase 2 task to provision (0-7). Each task's resources exist when stage >= task number."
  type        = number
  default     = 0
  validation {
    condition     = var.stage >= 0 && var.stage <= 7 && floor(var.stage) == var.stage
    error_message = "stage must be an integer between 0 and 7."
  }
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "model_id" {
  description = "Gateway model your agent uses (`uv run bootcamp.py llm models` lists them); the CLI passes your MODEL_ID or the class default."
  type        = string
}

variable "litellm_base_url" {
  description = "Opsfleet LiteLLM gateway URL (from the participant's gateway secret)."
  type        = string
  default     = ""
}

variable "build_dir" {
  description = "Directory holding mcp_server.zip / agent.zip produced by bootcamp.py."
  type        = string
  default     = "../../.build"
}

variable "memory_event_expiry_days" {
  type    = number
  default = 30
}

variable "eval_sampling_percentage" {
  type    = number
  default = 100
}

variable "policy_mode" {
  type    = string
  default = "ENFORCE"
  validation {
    condition     = contains(["ENFORCE", "LOG_ONLY"], var.policy_mode)
    error_message = "policy_mode must be ENFORCE or LOG_ONLY."
  }
}

variable "enable_code_interpreter" {
  description = "Optional: give the agent a run_python tool backed by the AWS-managed AgentCore Code Interpreter (stage >= 4)."
  type        = bool
  default     = false
}

variable "enable_browser" {
  description = "Optional: give the agent a browse_web tool backed by the AWS-managed AgentCore Browser (stage >= 4)."
  type        = bool
  default     = false
}

variable "enable_guardrails" {
  description = "Optional: a Bedrock Guardrail (prompt-attack filter + PII masking) on every agent model call (stage >= 4)."
  type        = bool
  default     = false
}

variable "guardrail_prompt_attack_strength" {
  description = "Optional guardrail: prompt-attack filter strength on user input (NONE, LOW, MEDIUM, HIGH); GUARDRAIL_PROMPT_ATTACK_STRENGTH in .env."
  type        = string
  default     = "MEDIUM"
  validation {
    condition     = contains(["NONE", "LOW", "MEDIUM", "HIGH"], var.guardrail_prompt_attack_strength)
    error_message = "guardrail_prompt_attack_strength must be NONE, LOW, MEDIUM or HIGH."
  }
}

variable "guardrail_pii_types" {
  description = "Optional guardrail: comma-separated Bedrock PII entity types masked in answers (empty = none); GUARDRAIL_PII_TYPES in .env."
  type        = string
  default     = "EMAIL,PHONE"
  validation {
    condition     = can(regex("^([A-Z_]+(,[A-Z_]+)*)?$", var.guardrail_pii_types))
    error_message = "guardrail_pii_types must be a comma-separated list of upper-case PII entity types, e.g. EMAIL,PHONE."
  }
}

variable "memory_episodic" {
  description = "Experiment: add an EPISODIC strategy to the memory (stage >= 3); MEMORY_EPISODIC in .env."
  type        = bool
  default     = false
}

variable "trust_actor_header" {
  description = "INSECURE experiment: forward the caller-set actor header and let the agent trust it (stage >= 4); TRUST_ACTOR_HEADER in .env."
  type        = bool
  default     = false
}
