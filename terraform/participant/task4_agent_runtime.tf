locals {
  actor_header          = "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Actor-Id"
  agent_request_headers = var.trust_actor_header ? ["Authorization", local.actor_header] : ["Authorization"]
  actor_header_env      = var.trust_actor_header ? { TRUST_ACTOR_HEADER = "true" } : {}
}

resource "aws_s3_object" "agent_code" {
  count  = local.t4 ? 1 : 0
  bucket = aws_s3_bucket.code[0].id
  key    = "agent/${filemd5("${var.build_dir}/agent.zip")}.zip"
  source = "${var.build_dir}/agent.zip"
}

data "aws_iam_policy_document" "agent" {
  source_policy_documents = [data.aws_iam_policy_document.runtime_base.json]
  statement {
    sid = "Memory"
    actions = [
      "bedrock-agentcore:CreateEvent", "bedrock-agentcore:GetEvent", "bedrock-agentcore:ListEvents",
      "bedrock-agentcore:RetrieveMemoryRecords", "bedrock-agentcore:ListMemoryRecords", "bedrock-agentcore:GetMemory",
      "bedrock-agentcore:ListSessions", "bedrock-agentcore:ListActors",
    ]
    resources = local.t3 ? [aws_bedrockagentcore_memory.this[0].arn] : ["*"]
  }
  statement {
    sid = "Identity"
    actions = [
      "bedrock-agentcore:GetResourceOauth2Token", "bedrock-agentcore:GetWorkloadAccessToken",
      "bedrock-agentcore:GetWorkloadAccessTokenForJWT", "bedrock-agentcore:GetWorkloadAccessTokenForUserId",
    ]
    resources = ["*"]
  }
  statement {
    sid       = "TokenVaultSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["arn:${local.partition}:secretsmanager:${var.aws_region}:${local.account_id}:secret:bedrock-agentcore-identity!default/oauth2/${local.prefix}-*"]
  }
}

resource "aws_iam_role" "agent_runtime" {
  count                = local.t4 ? 1 : 0
  name                 = "${local.prefix}-agent-runtime"
  assume_role_policy   = data.aws_iam_policy_document.agentcore_trust.json
  permissions_boundary = local.boundary_arn
}

resource "aws_iam_role_policy" "agent_runtime" {
  count  = local.t4 ? 1 : 0
  role   = aws_iam_role.agent_runtime[0].id
  policy = data.aws_iam_policy_document.agent.json
}

resource "aws_bedrockagentcore_agent_runtime" "agent" {
  count              = local.t4 ? 1 : 0
  agent_runtime_name = "${local.ac_prefix}_agent"
  role_arn           = aws_iam_role.agent_runtime[0].arn

  agent_runtime_artifact {
    code_configuration {
      entry_point = ["opentelemetry-instrument", "agent.py"]
      runtime     = "PYTHON_3_13"
      code {
        s3 {
          bucket = aws_s3_bucket.code[0].id
          prefix = aws_s3_object.agent_code[0].key
        }
      }
    }
  }

  environment_variables = merge(local.sandbox_env, local.guardrail_env, local.actor_header_env, {
    MODEL_ID                      = var.model_id
    LITELLM_BASE_URL              = var.litellm_base_url
    GATEWAY_URL                   = aws_bedrockagentcore_gateway.this[0].gateway_url
    MEMORY_ID                     = aws_bedrockagentcore_memory.this[0].id
    MEMORY_STRATEGY_ID            = aws_bedrockagentcore_memory_strategy.user_facts[0].memory_strategy_id
    MEMORY_PREFERENCE_STRATEGY_ID = aws_bedrockagentcore_memory_strategy.user_preferences[0].memory_strategy_id
    MEMORY_SUMMARY_STRATEGY_ID    = aws_bedrockagentcore_memory_strategy.session_summaries[0].memory_strategy_id
    CREDENTIAL_PROVIDER_NAME      = aws_bedrockagentcore_oauth2_credential_provider.mcp[0].name
    OAUTH_SCOPE                   = local.oauth_scope
  })

  authorizer_configuration {
    custom_jwt_authorizer {
      discovery_url   = local.discovery_url
      allowed_clients = [aws_cognito_user_pool_client.users.id]
    }
  }

  network_configuration { network_mode = "PUBLIC" }
  protocol_configuration { server_protocol = "HTTP" }
  request_header_configuration { request_header_allowlist = local.agent_request_headers }

  depends_on = [aws_iam_role_policy.agent_runtime, aws_iam_role_policy.agent_sandbox_tools]
}
