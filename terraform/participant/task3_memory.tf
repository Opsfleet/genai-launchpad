resource "aws_bedrockagentcore_memory" "this" {
  count                 = local.t3 ? 1 : 0
  name                  = "${local.ac_prefix}_memory"
  description           = "DataStream Corp memory for ${var.participant}"
  event_expiry_duration = var.memory_event_expiry_days
}

resource "aws_bedrockagentcore_workload_identity" "local" {
  count = local.t3 ? 1 : 0
  name  = "${local.prefix}-local"
}

resource "aws_bedrockagentcore_memory_strategy" "user_facts" {
  count               = local.t3 ? 1 : 0
  memory_id           = aws_bedrockagentcore_memory.this[0].id
  name                = "UserFacts"
  type                = "SEMANTIC"
  namespace_templates = ["/strategies/{memoryStrategyId}/actors/{actorId}"]
}

resource "aws_bedrockagentcore_memory_strategy" "user_preferences" {
  count               = local.t3 ? 1 : 0
  memory_id           = aws_bedrockagentcore_memory.this[0].id
  name                = "UserPreferences"
  type                = "USER_PREFERENCE"
  namespace_templates = ["/strategies/{memoryStrategyId}/actors/{actorId}"]
  depends_on          = [aws_bedrockagentcore_memory_strategy.user_facts]
}

resource "aws_bedrockagentcore_memory_strategy" "session_summaries" {
  count               = local.t3 ? 1 : 0
  memory_id           = aws_bedrockagentcore_memory.this[0].id
  name                = "SessionSummaries"
  type                = "SUMMARIZATION"
  namespace_templates = ["/strategies/{memoryStrategyId}/actors/{actorId}/sessions/{sessionId}"]
  depends_on          = [aws_bedrockagentcore_memory_strategy.user_preferences]
}

resource "aws_bedrockagentcore_memory_strategy" "episodes" {
  count               = local.t3 && var.memory_episodic ? 1 : 0
  memory_id           = aws_bedrockagentcore_memory.this[0].id
  name                = "Episodes"
  type                = "EPISODIC"
  namespace_templates = ["/strategies/{memoryStrategyId}/actors/{actorId}/sessions/{sessionId}"]
  depends_on          = [aws_bedrockagentcore_memory_strategy.session_summaries]
}
