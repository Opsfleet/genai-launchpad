# Task 2 Part B: the weather tool as a second Gateway target of another type (Lambda), next to the MCP-runtime target.
locals {
  weather_tools    = jsondecode(file("${path.module}/../../phase2/app/weather_lambda/tools.json"))
  weather_function = "${local.prefix}-weather"
}

data "aws_iam_policy_document" "lambda_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

data "aws_iam_policy_document" "weather_lambda" {
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:${local.partition}:logs:${var.aws_region}:${local.account_id}:log-group:/aws/lambda/${local.weather_function}:*"]
  }
}

resource "aws_iam_role" "weather_lambda" {
  count                = local.t2 ? 1 : 0
  name                 = "${local.prefix}-weather-lambda"
  assume_role_policy   = data.aws_iam_policy_document.lambda_trust.json
  permissions_boundary = local.boundary_arn
}

resource "aws_iam_role_policy" "weather_lambda" {
  count  = local.t2 ? 1 : 0
  role   = aws_iam_role.weather_lambda[0].id
  policy = data.aws_iam_policy_document.weather_lambda.json
}

resource "aws_cloudwatch_log_group" "weather" {
  count             = local.t2 ? 1 : 0
  name              = "/aws/lambda/${local.weather_function}"
  retention_in_days = 7
}

resource "aws_lambda_function" "weather" {
  count            = local.t2 ? 1 : 0
  function_name    = local.weather_function
  description      = "DataStream weather tools (NWS) behind the AgentCore Gateway"
  role             = aws_iam_role.weather_lambda[0].arn
  filename         = "${var.build_dir}/weather_lambda.zip"
  source_code_hash = filebase64sha256("${var.build_dir}/weather_lambda.zip")
  handler          = "handler.handler"
  runtime          = "python3.13"
  architectures    = ["arm64"]
  memory_size      = 256
  timeout          = 30

  depends_on = [aws_iam_role_policy.weather_lambda, aws_cloudwatch_log_group.weather]
}

resource "aws_bedrockagentcore_gateway_target" "weather" {
  count              = local.t2 ? 1 : 0
  gateway_identifier = aws_bedrockagentcore_gateway.this[0].gateway_id
  name               = "Weather"
  description        = "US weather forecasts from the National Weather Service"

  target_configuration {
    mcp {
      lambda {
        lambda_arn = aws_lambda_function.weather[0].arn
        tool_schema {
          dynamic "inline_payload" {
            for_each = local.weather_tools
            content {
              name        = inline_payload.value.name
              description = inline_payload.value.description
              input_schema {
                type = "object"
                dynamic "property" {
                  for_each = inline_payload.value.inputSchema.properties
                  content {
                    name        = property.key
                    type        = property.value.type
                    description = try(property.value.description, null)
                    required    = contains(try(inline_payload.value.inputSchema.required, []), property.key)
                  }
                }
              }
            }
          }
        }
      }
    }
  }

  credential_provider_configuration {
    gateway_iam_role {}
  }

  depends_on = [aws_iam_role_policy.gateway]
}
