locals {
  prefix        = "awsworkshop-${var.participant}"
  ac_prefix     = "awsworkshop_${var.participant}"
  account_id    = data.aws_caller_identity.current.account_id
  partition     = data.aws_partition.current.partition
  code_bucket   = "${local.prefix}-code-${local.account_id}-${var.aws_region}"
  boundary_arn  = "arn:${local.partition}:iam::${local.account_id}:policy/bootcamp/bootcamp-workload-boundary"
  eval_role_arn = "arn:${local.partition}:iam::${local.account_id}:role/bootcamp/bootcamp-eval-${var.participant}"
  db_key        = "db/datastream_corp.db"

  t1 = var.stage >= 1
  t2 = var.stage >= 2
  t3 = var.stage >= 3
  t4 = var.stage >= 4
  t5 = var.stage >= 5
  t6 = var.stage >= 6
  t7 = var.stage >= 7

  oauth_scope          = "datastream/mcp.access"
  cognito_issuer       = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.this.id}"
  discovery_url        = "${local.cognito_issuer}/.well-known/openid-configuration"
  cognito_base_url     = "https://${aws_cognito_user_pool_domain.this.domain}.auth.${var.aws_region}.amazoncognito.com"
  story_users          = ["alice-chen", "jordan-lee"]
  users_parameter_path = "/workshop/${local.prefix}-users"

  tags = {
    Project     = "genai-bootcamp"
    Participant = var.participant
    ManagedBy   = "terraform"
  }
}
