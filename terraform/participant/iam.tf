data "aws_iam_policy_document" "agentcore_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

data "aws_iam_policy_document" "runtime_base" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams", "logs:DescribeLogGroups"]
    resources = ["arn:${local.partition}:logs:${var.aws_region}:${local.account_id}:log-group:*"]
  }
  statement {
    sid       = "Telemetry"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets", "cloudwatch:PutMetricData"]
    resources = ["*"]
  }
  statement {
    sid       = "ReadCode"
    actions   = ["s3:GetObject"]
    resources = ["arn:${local.partition}:s3:::${local.code_bucket}/*"]
  }
}
