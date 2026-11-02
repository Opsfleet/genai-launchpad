variable "online_code_evaluator" {
  description = "Also score live traffic with your code-based evaluators (the platform's bootcamp-eval-<you> role may invoke awsworkshop-<you>-* Lambdas); `eval` uses them either way. Every scored live turn costs one rubric_judge call on your LiteLLM budget."
  type        = bool
  default     = true
}

variable "judge_model" {
  description = "Gateway model the rubric_judge evaluator asks (billed to your LiteLLM budget); empty = your model_id."
  type        = string
  default     = ""
}

variable "judge_rubric" {
  description = "Entry of phase2/evals/evaluators.yaml the rubric_judge evaluator scores with."
  type        = string
  default     = "datastream_rubric"
}

locals {
  builtin_evaluators = ["Builtin.Helpfulness", "Builtin.GoalSuccessRate", "Builtin.Correctness"]
  code_evaluators = {
    exact_numbers = {
      app         = "code_evaluator"
      function    = "${local.prefix}-code-evaluator"
      description = "Code-based (Lambda): every expected number appears in the answer; no unfilled placeholders"
      environment = {}
    }
    rubric_judge = {
      app         = "rubric_judge"
      function    = "${local.prefix}-rubric-judge"
      description = "LLM-as-a-judge through LiteLLM (Lambda): a rubric of phase2/evals/evaluators.yaml"
      environment = {
        LITELLM_BASE_URL = var.litellm_base_url
        JUDGE_MODEL      = var.judge_model != "" ? var.judge_model : var.model_id
        JUDGE_RUBRIC     = var.judge_rubric
      }
    }
  }
  t6_code_evaluators = local.t6 ? local.code_evaluators : {}
}

moved {
  from = aws_iam_role.code_evaluator[0]
  to   = aws_iam_role.code_evaluator["exact_numbers"]
}

moved {
  from = aws_iam_role_policy.code_evaluator[0]
  to   = aws_iam_role_policy.code_evaluator["exact_numbers"]
}

moved {
  from = aws_cloudwatch_log_group.code_evaluator[0]
  to   = aws_cloudwatch_log_group.code_evaluator["exact_numbers"]
}

moved {
  from = aws_lambda_function.code_evaluator[0]
  to   = aws_lambda_function.code_evaluator["exact_numbers"]
}

moved {
  from = aws_bedrockagentcore_evaluator.code[0]
  to   = aws_bedrockagentcore_evaluator.code["exact_numbers"]
}

resource "aws_iam_role" "code_evaluator" {
  for_each             = local.t6_code_evaluators
  name                 = each.value.function
  assume_role_policy   = data.aws_iam_policy_document.lambda_trust.json
  permissions_boundary = local.boundary_arn
}

resource "aws_iam_role_policy" "code_evaluator" {
  for_each = local.t6_code_evaluators
  role     = aws_iam_role.code_evaluator[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = "arn:${local.partition}:logs:${var.aws_region}:${local.account_id}:log-group:/aws/lambda/${each.value.function}:*"
    }]
  })
}

resource "aws_cloudwatch_log_group" "code_evaluator" {
  for_each          = local.t6_code_evaluators
  name              = "/aws/lambda/${each.value.function}"
  retention_in_days = 7
}

resource "aws_lambda_function" "code_evaluator" {
  for_each         = local.t6_code_evaluators
  function_name    = each.value.function
  description      = each.value.description
  role             = aws_iam_role.code_evaluator[each.key].arn
  filename         = "${var.build_dir}/${each.value.app}.zip"
  source_code_hash = filebase64sha256("${var.build_dir}/${each.value.app}.zip")
  handler          = "handler.handler"
  runtime          = "python3.13"
  architectures    = ["arm64"]
  memory_size      = 256
  timeout          = 60

  dynamic "environment" {
    for_each = length(each.value.environment) > 0 ? [each.value.environment] : []
    content { variables = environment.value }
  }

  depends_on = [aws_iam_role_policy.code_evaluator, aws_cloudwatch_log_group.code_evaluator]
}

resource "aws_bedrockagentcore_evaluator" "code" {
  for_each       = local.t6_code_evaluators
  evaluator_name = "${local.ac_prefix}_${each.key}"
  description    = each.value.description
  level          = "TRACE"

  evaluator_config {
    code_based {
      lambda_config {
        lambda_arn                = aws_lambda_function.code_evaluator[each.key].arn
        lambda_timeout_in_seconds = 60
      }
    }
  }
}

resource "aws_bedrockagentcore_online_evaluation_config" "this" {
  count                         = local.t6 ? 1 : 0
  online_evaluation_config_name = "${local.ac_prefix}_quality"
  description                   = "Production quality monitoring for DataStream Corp"
  evaluation_execution_role_arn = local.eval_role_arn
  enable_on_create              = true

  data_source_config {
    cloudwatch_logs {
      log_group_names = ["/aws/bedrock-agentcore/runtimes/${aws_bedrockagentcore_agent_runtime.agent[0].agent_runtime_id}-DEFAULT"]
      service_names   = ["${aws_bedrockagentcore_agent_runtime.agent[0].agent_runtime_name}.DEFAULT"]
    }
  }

  dynamic "evaluator" {
    for_each = toset(concat(
      local.builtin_evaluators,
      [for evaluator in aws_bedrockagentcore_evaluator.code : evaluator.evaluator_id if var.online_code_evaluator],
    ))
    content { evaluator_id = evaluator.value }
  }

  rule {
    sampling_config { sampling_percentage = var.eval_sampling_percentage }
  }

}

output "custom_evaluators" {
  description = "Your custom evaluators (name -> id) for `bootcamp.py eval --evaluators custom`."
  value       = { for name, item in aws_bedrockagentcore_evaluator.code : name => item.evaluator_id }
}
