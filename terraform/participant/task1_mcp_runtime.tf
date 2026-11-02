resource "aws_s3_bucket" "code" {
  count         = local.t1 ? 1 : 0
  bucket        = local.code_bucket
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "code" {
  count                   = local.t1 ? 1 : 0
  bucket                  = aws_s3_bucket.code[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_object" "mcp_code" {
  count  = local.t1 ? 1 : 0
  bucket = aws_s3_bucket.code[0].id
  key    = "mcp_server/${filemd5("${var.build_dir}/mcp_server.zip")}.zip"
  source = "${var.build_dir}/mcp_server.zip"
}

resource "aws_iam_role" "mcp_runtime" {
  count                = local.t1 ? 1 : 0
  name                 = "${local.prefix}-mcp-runtime"
  assume_role_policy   = data.aws_iam_policy_document.agentcore_trust.json
  permissions_boundary = local.boundary_arn
}

resource "aws_s3_object" "database" {
  count  = local.t1 ? 1 : 0
  bucket = aws_s3_bucket.code[0].id
  key    = local.db_key
  source = "${var.build_dir}/datastream_corp.db"
  lifecycle { ignore_changes = [source, etag] }
}

data "aws_iam_policy_document" "mcp_runtime" {
  source_policy_documents = [data.aws_iam_policy_document.runtime_base.json]
  statement {
    sid       = "OwnDatabase"
    actions   = ["s3:GetObject"]
    resources = ["arn:${local.partition}:s3:::${local.code_bucket}/${local.db_key}"]
  }
}

resource "aws_iam_role_policy" "mcp_runtime" {
  count  = local.t1 ? 1 : 0
  role   = aws_iam_role.mcp_runtime[0].id
  policy = data.aws_iam_policy_document.mcp_runtime.json
}

resource "aws_bedrockagentcore_agent_runtime" "mcp" {
  count              = local.t1 ? 1 : 0
  agent_runtime_name = "${local.ac_prefix}_mcp_server"
  role_arn           = aws_iam_role.mcp_runtime[0].arn

  agent_runtime_artifact {
    code_configuration {
      entry_point = ["mcp_server.py"]
      runtime     = "PYTHON_3_13"
      code {
        s3 {
          bucket = aws_s3_bucket.code[0].id
          prefix = aws_s3_object.mcp_code[0].key
        }
      }
    }
  }

  authorizer_configuration {
    custom_jwt_authorizer {
      discovery_url   = local.discovery_url
      allowed_clients = [aws_cognito_user_pool_client.this.id]
    }
  }

  environment_variables = { DB_BUCKET = local.code_bucket, DB_KEY = local.db_key }

  network_configuration { network_mode = "PUBLIC" }
  protocol_configuration { server_protocol = "MCP" }
  request_header_configuration { request_header_allowlist = ["Authorization"] }

  depends_on = [aws_iam_role_policy.mcp_runtime]
}

locals {
  mcp_runtime_url = local.t1 ? "https://bedrock-agentcore.${var.aws_region}.amazonaws.com/runtimes/${urlencode(aws_bedrockagentcore_agent_runtime.mcp[0].agent_runtime_arn)}/invocations?qualifier=DEFAULT" : ""
}
