locals {
  code_interpreter_on  = local.t4 && var.enable_code_interpreter
  browser_on           = local.t4 && var.enable_browser
  code_interpreter_id  = "aws.codeinterpreter.v1"
  browser_id           = "aws.browser.v1"
  code_interpreter_arn = "arn:${local.partition}:bedrock-agentcore:${var.aws_region}:aws:code-interpreter/${local.code_interpreter_id}"
  browser_arn          = "arn:${local.partition}:bedrock-agentcore:${var.aws_region}:aws:browser/${local.browser_id}"

  sandbox_env = merge(
    { CODE_INTERPRETER_ENABLED = tostring(local.code_interpreter_on), BROWSER_ENABLED = tostring(local.browser_on) },
    local.code_interpreter_on ? { CODE_INTERPRETER_ID = local.code_interpreter_id } : {},
    local.browser_on ? { BROWSER_ID = local.browser_id } : {},
  )
}

data "aws_iam_policy_document" "sandbox_tools" {
  dynamic "statement" {
    for_each = local.code_interpreter_on ? [1] : []
    content {
      sid = "CodeInterpreterSessions"
      actions = [
        "bedrock-agentcore:StartCodeInterpreterSession", "bedrock-agentcore:StopCodeInterpreterSession",
        "bedrock-agentcore:GetCodeInterpreterSession", "bedrock-agentcore:InvokeCodeInterpreter",
      ]
      resources = [local.code_interpreter_arn]
    }
  }
  dynamic "statement" {
    for_each = local.browser_on ? [1] : []
    content {
      sid = "BrowserSessions"
      actions = [
        "bedrock-agentcore:StartBrowserSession", "bedrock-agentcore:StopBrowserSession",
        "bedrock-agentcore:GetBrowserSession", "bedrock-agentcore:ConnectBrowserAutomationStream",
      ]
      resources = [local.browser_arn]
    }
  }
}

resource "aws_iam_role_policy" "agent_sandbox_tools" {
  count  = local.code_interpreter_on || local.browser_on ? 1 : 0
  name   = "${local.prefix}-sandbox-tools"
  role   = aws_iam_role.agent_runtime[0].id
  policy = data.aws_iam_policy_document.sandbox_tools.json
}
