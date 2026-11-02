resource "aws_cognito_user_pool_client" "users" {
  name                = "${local.prefix}-users"
  user_pool_id        = aws_cognito_user_pool.this.id
  generate_secret     = false
  explicit_auth_flows = ["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
}

resource "random_password" "user" {
  for_each         = toset(local.story_users)
  length           = 24
  min_upper        = 1
  min_lower        = 1
  min_numeric      = 1
  min_special      = 1
  override_special = "!#%+-_="
}

resource "aws_cognito_user" "story" {
  for_each       = toset(local.story_users)
  user_pool_id   = aws_cognito_user_pool.this.id
  username       = each.key
  password       = random_password.user[each.key].result
  message_action = "SUPPRESS"
}

resource "aws_ssm_parameter" "user_password" {
  for_each    = toset(local.story_users)
  name        = "${local.users_parameter_path}/${each.key}"
  description = "Cognito password of the DataStream story user ${each.key} (bootcamp.py invoke --actor signs in with it)"
  type        = "SecureString"
  value       = random_password.user[each.key].result
}
