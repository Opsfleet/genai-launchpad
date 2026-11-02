resource "aws_bedrockagentcore_policy_engine" "this" {
  count       = local.t7 ? 1 : 0
  name        = "${local.ac_prefix}_policy_engine"
  description = "Database governance for ${var.participant}"
}

resource "aws_bedrockagentcore_policy" "safe_query" {
  count            = local.t7 ? 1 : 0
  policy_engine_id = aws_bedrockagentcore_policy_engine.this[0].policy_engine_id
  name             = "${local.ac_prefix}_safe_query_policy"
  description      = "Allow only SELECT queries; block DELETE/DROP/UPDATE"

  definition {
    cedar {
      statement = templatefile("${path.module}/safe_query_policy.cedar", {
        action      = "${aws_bedrockagentcore_gateway_target.database[0].name}___query_db"
        gateway_arn = aws_bedrockagentcore_gateway.this[0].gateway_arn
      })
    }
  }
}

locals {
  mcp_source   = file("${path.module}/../../phase2/app/mcp_server/mcp_server.py")
  schema_tools = [for name in ["list_tables", "describe_table"] : name if length(regexall("def\\s+${name}\\s*\\(", local.mcp_source)) > 0]
}

resource "aws_bedrockagentcore_policy" "schema_tools" {
  count            = local.t7 && length(local.schema_tools) > 0 ? 1 : 0
  policy_engine_id = aws_bedrockagentcore_policy_engine.this[0].policy_engine_id
  name             = "${local.ac_prefix}_schema_tools_policy"
  description      = "Allow the read-only schema tools your MCP server defines: ${join(", ", local.schema_tools)}"

  definition {
    cedar {
      statement = templatefile("${path.module}/schema_tools_policy.cedar", {
        actions     = join(", ", [for name in local.schema_tools : "AgentCore::Action::\"${aws_bedrockagentcore_gateway_target.database[0].name}___${name}\""])
        gateway_arn = aws_bedrockagentcore_gateway.this[0].gateway_arn
      })
    }
  }

  depends_on = [terraform_data.gateway_tool_sync]
}

resource "aws_bedrockagentcore_policy" "weather_tools" {
  count            = local.t7 ? 1 : 0
  policy_engine_id = aws_bedrockagentcore_policy_engine.this[0].policy_engine_id
  name             = "${local.ac_prefix}_weather_tools_policy"
  description      = "Allow every tool of the Weather Lambda target (phase2/app/weather_lambda/tools.json)"

  definition {
    cedar {
      statement = templatefile("${path.module}/schema_tools_policy.cedar", {
        actions     = join(", ", [for tool in local.weather_tools : "AgentCore::Action::\"${aws_bedrockagentcore_gateway_target.weather[0].name}___${tool.name}\""])
        gateway_arn = aws_bedrockagentcore_gateway.this[0].gateway_arn
      })
    }
  }
}
