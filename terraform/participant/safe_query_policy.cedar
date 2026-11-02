permit(
  principal,
  action == AgentCore::Action::"${action}",
  resource == AgentCore::Gateway::"${gateway_arn}"
)
when {
  (
    context.input.query like "SELECT *" || context.input.query like "SELECT\n*" || context.input.query like "SELECT\t*" || context.input.query like "SELECT\r*" ||
    context.input.query like "select *" || context.input.query like "select\n*" || context.input.query like "select\t*" || context.input.query like "select\r*" ||
    context.input.query like "Select *" || context.input.query like "Select\n*" || context.input.query like "Select\t*" || context.input.query like "Select\r*" ||
    context.input.query like "WITH *" || context.input.query like "WITH\n*" || context.input.query like "WITH\t*" || context.input.query like "WITH\r*" ||
    context.input.query like "with *" || context.input.query like "with\n*" || context.input.query like "with\t*" || context.input.query like "with\r*" ||
    context.input.query like "With *" || context.input.query like "With\n*" || context.input.query like "With\t*" || context.input.query like "With\r*" ||
    context.input.query like "EXPLAIN *" || context.input.query like "EXPLAIN\n*" || context.input.query like "EXPLAIN\t*" || context.input.query like "EXPLAIN\r*" ||
    context.input.query like "explain *" || context.input.query like "explain\n*" || context.input.query like "explain\t*" || context.input.query like "explain\r*" ||
    context.input.query like "Explain *" || context.input.query like "Explain\n*" || context.input.query like "Explain\t*" || context.input.query like "Explain\r*" ||
    ((context.input.query like "PRAGMA table_info(*" || context.input.query like "pragma table_info(*" || context.input.query like "Pragma table_info(*") &&
     !(context.input.query like "*=*" || context.input.query like "*;*"))
  ) &&
  !(context.input.query like "*--*" || context.input.query like "*/\**") &&
  !(context.input.query like "*INSERT *" || context.input.query like "*INSERT\t*" || context.input.query like "*INSERT\n*" || context.input.query like "*INSERT\r*") &&
  !(context.input.query like "*insert *" || context.input.query like "*insert\t*" || context.input.query like "*insert\n*" || context.input.query like "*insert\r*") &&
  !(context.input.query like "*Insert *" || context.input.query like "*Insert\t*" || context.input.query like "*Insert\n*" || context.input.query like "*Insert\r*") &&
  !(context.input.query like "*UPDATE *" || context.input.query like "*UPDATE\t*" || context.input.query like "*UPDATE\n*" || context.input.query like "*UPDATE\r*") &&
  !(context.input.query like "*update *" || context.input.query like "*update\t*" || context.input.query like "*update\n*" || context.input.query like "*update\r*") &&
  !(context.input.query like "*Update *" || context.input.query like "*Update\t*" || context.input.query like "*Update\n*" || context.input.query like "*Update\r*") &&
  !(context.input.query like "*DELETE *" || context.input.query like "*DELETE\t*" || context.input.query like "*DELETE\n*" || context.input.query like "*DELETE\r*") &&
  !(context.input.query like "*delete *" || context.input.query like "*delete\t*" || context.input.query like "*delete\n*" || context.input.query like "*delete\r*") &&
  !(context.input.query like "*Delete *" || context.input.query like "*Delete\t*" || context.input.query like "*Delete\n*" || context.input.query like "*Delete\r*") &&
  !(context.input.query like "*REPLACE *" || context.input.query like "*REPLACE\t*" || context.input.query like "*REPLACE\n*" || context.input.query like "*REPLACE\r*") &&
  !(context.input.query like "*replace *" || context.input.query like "*replace\t*" || context.input.query like "*replace\n*" || context.input.query like "*replace\r*") &&
  !(context.input.query like "*Replace *" || context.input.query like "*Replace\t*" || context.input.query like "*Replace\n*" || context.input.query like "*Replace\r*") &&
  !(context.input.query like "*DROP *" || context.input.query like "*DROP\t*" || context.input.query like "*DROP\n*" || context.input.query like "*DROP\r*") &&
  !(context.input.query like "*drop *" || context.input.query like "*drop\t*" || context.input.query like "*drop\n*" || context.input.query like "*drop\r*") &&
  !(context.input.query like "*Drop *" || context.input.query like "*Drop\t*" || context.input.query like "*Drop\n*" || context.input.query like "*Drop\r*")
};
