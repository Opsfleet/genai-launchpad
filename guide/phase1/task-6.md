Task 6 · 8 tasks
# Structured output
Make the agent return a typed Pydantic DepartmentReport instead of a wall of text.
20 minMedium
Alice’s ask
## The “Messy Handwriting” problem
Alice asked for a department report and got three paragraphs of prose. Her dashboard needs JSON with a known shape. Time to give the agent a contract.
You
## Build it
### Return a typed report
Challenge
Define a `DepartmentReport` with a title, a summary, a list of `Department` entries (name and active employees) and an integer `total_employees`, reject a report whose total is not the sum of its departments, and make the agent return one.
Work in `phase1/starter/t6_structured_output.py` (look for `TODO`; an unfinished one prints `[starter] TODO …`) and run it with `uv run bootcamp.py phase1 t6 --starter`. The reference solution is `phase1/t6_structured_output.py`; `uv run bootcamp.py phase1 t6` runs it.
Docs
- Strands: structured output (https://strandsagents.com/docs/user-guide/sdk/agents/structured-output/)
#### Hint 1
Strands can validate the final answer against a Pydantic model. See Strands: structured output (https://strandsagents.com/docs/user-guide/sdk/agents/structured-output/).
#### Hint 2
Pass `structured_output_model=DepartmentReport` when you call the agent and read `result.structured_output`. `Field(description=...)` tells the model what each field means (say “every department, including those with no active employees”).
#### Hint 3
A Pydantic `@model_validator(mode="after")` can check fields against each other; raise `ValueError` with a clear message. Strands sends that message back to the model as the tool's error, and the model tries again.
#### Solution: on the task page (open it only when the participant asks for the solution)
### Run it

terminal · your starter file:
```bash
uv run bootcamp.py phase1 t6 --starter "Generate a department report for DataStream Corp"
```

terminal · reference solution:
```bash
uv run bootcamp.py phase1 t6 "Generate a department report for DataStream Corp"
```

### Experiments
- Watch the validator reject a bad report without spending a token:

terminal:
```bash
uv run python -c "import sys; sys.path.insert(0, 'phase1'); from t6_structured_output import DepartmentReport; DepartmentReport(title='t', summary='s', total_employees=100, departments=[{'name': 'HR', 'active_employees': 84}])"
```

In a real run the same message comes back as `[tool] DepartmentReport error: ... total_employees is ..., but the departments add up to ...`, followed by a second `[tool] DepartmentReport` call with the fixed report.
- Add a `budget` to `Department`. Does the agent run another query to fill it?
- Add a field the data can't support, like `customer_satisfaction`. What does the model put there? Would `Optional` plus a clear description help?
## Check your work
Phase 1 has no automated test: you check it by running the task and looking for the result below.
The `[tool] query_db` lines count `status = 'active'`, then a `[tool] DepartmentReport` line hands over the report. The printed JSON lists all seven departments with their active employees (Engineering 481, Sales 360, Marketing 180, HR 84, Finance 60, Operations 36 and Research 0: **1,201** in total), and `total_employees` is **1201**, the sum of the department counts. A missing Research row, 483 for Engineering or a total of 1207 means the agent counted the wrong rows: the report validates but is wrong.
Failed? Run the same prompt on the reference (drop `--starter`). If the reference fails too, it's the model: rerun or try another `MODEL_ID` (`uv run bootcamp.py llm models`).
#### Under the hood
Strands turns the Pydantic model into a tool schema and asks the model to call it as its final step, then validates the arguments with Pydantic, including your `model_validator`. If validation fails, the error is fed back as the tool result so the model can retry. You get a real Python object, not text you have to parse.
