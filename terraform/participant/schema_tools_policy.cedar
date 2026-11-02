permit(
  principal,
  action in [${actions}],
  resource == AgentCore::Gateway::"${gateway_arn}"
);
