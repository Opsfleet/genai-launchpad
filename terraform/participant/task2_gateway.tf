data "aws_iam_policy_document" "gateway" {
  statement {
    actions   = ["bedrock-agentcore:*"]
    resources = ["*"]
  }
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["arn:${local.partition}:secretsmanager:${var.aws_region}:${local.account_id}:secret:bedrock-agentcore-identity!default/oauth2/${local.prefix}-*"]
  }
  statement {
    sid       = "InvokeLambdaTargets"
    actions   = ["lambda:InvokeFunction"]
    resources = ["arn:${local.partition}:lambda:${var.aws_region}:${local.account_id}:function:${local.prefix}-*"]
  }
}

resource "aws_iam_role" "gateway" {
  count                = local.t2 ? 1 : 0
  name                 = "${local.prefix}-gateway"
  assume_role_policy   = data.aws_iam_policy_document.agentcore_trust.json
  permissions_boundary = local.boundary_arn
}

resource "aws_iam_role_policy" "gateway" {
  count  = local.t2 ? 1 : 0
  role   = aws_iam_role.gateway[0].id
  policy = data.aws_iam_policy_document.gateway.json
}

resource "aws_bedrockagentcore_oauth2_credential_provider" "mcp" {
  count                      = local.t2 ? 1 : 0
  name                       = "${local.prefix}-mcp-identity"
  credential_provider_vendor = "CustomOauth2"
  oauth2_provider_config {
    custom_oauth2_provider_config {
      client_id     = aws_cognito_user_pool_client.this.id
      client_secret = aws_cognito_user_pool_client.this.client_secret
      oauth_discovery {
        authorization_server_metadata {
          issuer                 = local.cognito_issuer
          token_endpoint         = "${local.cognito_base_url}/oauth2/token"
          authorization_endpoint = "${local.cognito_base_url}/oauth2/authorize"
          response_types         = ["token"]
        }
      }
    }
  }
  lifecycle { replace_triggered_by = [aws_cognito_user_pool_domain.this] }
}

resource "aws_bedrockagentcore_gateway" "this" {
  count           = local.t2 ? 1 : 0
  name            = "${local.prefix}-gateway"
  protocol_type   = "MCP"
  authorizer_type = "CUSTOM_JWT"
  role_arn        = aws_iam_role.gateway[0].arn

  protocol_configuration {
    mcp { search_type = "SEMANTIC" }
  }

  authorizer_configuration {
    custom_jwt_authorizer {
      discovery_url   = local.discovery_url
      allowed_clients = [aws_cognito_user_pool_client.this.id]
    }
  }

  dynamic "policy_engine_configuration" {
    for_each = local.t7 ? [1] : []
    content {
      arn  = aws_bedrockagentcore_policy_engine.this[0].policy_engine_arn
      mode = var.policy_mode
    }
  }

  depends_on = [aws_iam_role_policy.gateway]
}

resource "aws_bedrockagentcore_gateway_target" "database" {
  count              = local.t2 ? 1 : 0
  gateway_identifier = aws_bedrockagentcore_gateway.this[0].gateway_id
  name               = "DataStreamDatabase"

  target_configuration {
    mcp {
      mcp_server { endpoint = local.mcp_runtime_url }
    }
  }

  credential_provider_configuration {
    oauth {
      provider_arn = aws_bedrockagentcore_oauth2_credential_provider.mcp[0].credential_provider_arn
      grant_type   = "CLIENT_CREDENTIALS"
      scopes       = [local.oauth_scope]
    }
  }
}

resource "terraform_data" "gateway_tool_sync" {
  count            = local.t2 ? 1 : 0
  triggers_replace = [aws_bedrockagentcore_agent_runtime.mcp[0].agent_runtime_version]

  provisioner "local-exec" {
    command     = "uv run python -m bootcamp_cli.agentcore sync-gateway ${aws_bedrockagentcore_gateway.this[0].gateway_id} ${aws_bedrockagentcore_gateway_target.database[0].target_id}"
    working_dir = "${path.module}/../.."
  }

  depends_on = [aws_bedrockagentcore_gateway_target.database]
}
