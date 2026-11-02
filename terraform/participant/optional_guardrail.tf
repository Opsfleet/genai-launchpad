locals {
  guardrails_on = local.t4 && var.enable_guardrails
  pii_types     = compact(split(",", var.guardrail_pii_types))

  guardrail_env = local.guardrails_on ? {
    GUARDRAIL_ID      = aws_bedrock_guardrail.this[0].guardrail_id
    GUARDRAIL_VERSION = aws_bedrock_guardrail_version.this[0].version
  } : {}
}

resource "aws_bedrock_guardrail" "this" {
  count                     = local.guardrails_on ? 1 : 0
  name                      = "${local.prefix}-guardrail"
  description               = "DataStream agent: prompt-attack filter (${var.guardrail_prompt_attack_strength}), PII masked: ${join(", ", local.pii_types)}."
  blocked_input_messaging   = "Blocked by the DataStream guardrail: this request looks like a prompt attack."
  blocked_outputs_messaging = "Blocked by the DataStream guardrail."

  dynamic "content_policy_config" {
    for_each = var.guardrail_prompt_attack_strength == "NONE" ? [] : [var.guardrail_prompt_attack_strength]
    content {
      filters_config {
        type            = "PROMPT_ATTACK"
        input_strength  = content_policy_config.value
        output_strength = "NONE"
      }
    }
  }

  dynamic "sensitive_information_policy_config" {
    for_each = length(local.pii_types) > 0 ? [1] : []
    content {
      dynamic "pii_entities_config" {
        for_each = local.pii_types
        content {
          type   = pii_entities_config.value
          action = "ANONYMIZE"
        }
      }
    }
  }

  tags = local.tags
}

resource "aws_bedrock_guardrail_version" "this" {
  count         = local.guardrails_on ? 1 : 0
  guardrail_arn = aws_bedrock_guardrail.this[0].guardrail_arn
  description   = "Pinned by the agent runtime (GUARDRAIL_VERSION)."

  lifecycle {
    replace_triggered_by = [aws_bedrock_guardrail.this[count.index]]
  }
}
