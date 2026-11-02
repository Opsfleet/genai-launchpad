resource "aws_cognito_user_pool" "this" {
  name = "${local.prefix}-pool"
  password_policy { minimum_length = 8 }
}

resource "aws_cognito_resource_server" "this" {
  user_pool_id = aws_cognito_user_pool.this.id
  identifier   = "datastream"
  name         = "${local.prefix}-mcp"
  scope {
    scope_name        = "mcp.access"
    scope_description = "Access DataStream MCP tools"
  }
}

resource "aws_cognito_user_pool_client" "this" {
  name                                 = "${local.prefix}-client"
  user_pool_id                         = aws_cognito_user_pool.this.id
  generate_secret                      = true
  allowed_oauth_flows                  = ["client_credentials"]
  allowed_oauth_scopes                 = [local.oauth_scope]
  allowed_oauth_flows_user_pool_client = true
  supported_identity_providers         = ["COGNITO"]
  access_token_validity                = 8
  token_validity_units { access_token = "hours" }
  depends_on = [aws_cognito_resource_server.this]
}

resource "aws_cognito_user_pool_domain" "this" {
  domain       = "ds-${substr(sha1(var.participant), 0, 10)}-${local.account_id}"
  user_pool_id = aws_cognito_user_pool.this.id
}
