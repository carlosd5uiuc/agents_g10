````md
# Project README

This project contains an MCP server, task descriptions, tool schemas, sample agent outputs, and a grader script for evaluating agent performance.

## Project Structure

```text
.
├── mcp-server/
│   ├── resource_data/
│   ├── main.py
│   ├── pyproject.toml
│   ├── uv.lock
│   └── README.md
├── tasks/
│   └── task_01.json
├── tools/
│   └── example_tool.json
├── grader.py
├── tasks_description.json
├── tasks_example.json
└── tool_schema.json
````

## `mcp-server/`

The `mcp-server` folder contains the MCP server used by the agent.

The server runs with `uv`.

```bash
cd mcp-server
uv run main.py
```

### `mcp-server/resource_data/`

The `resource_data` folder stores the data used by each task.

Each task may have:

* a set of tools
* a set of resources

The data inside `resource_data` feeds the MCP resources used by the agent.

### `mcp-server/main.py`

The definition of each MCP tool and resource is located in:

```text
mcp-server/main.py
```

This file defines what tools the agent can call and what resources the agent can read.

## `grader.py`

`grader.py` is the script used to run and grade the agent output.

It should be passed a file located at the same directory level as `grader.py`.

Example:

```bash
python grader.py tasks_example.json
```

## `tasks_description.json`

`tasks_description.json` describes each task.

For the agent, the full task prompt should be built dynamically from this file. The generated prompt should include:

* `prompt`
* `hard_constraints`
* `preferences`
* `output_structure`

The final agent output must follow the structure defined in `output_structure`.

## `tasks_example.json`

`tasks_example.json` contains sample agent outputs.

These outputs are used to test `grader.py`.

## `tool_schema.json`

`tool_schema.json` contains the tool schema structure used by the agent.

This schema defines how tools should be represented when passed to the agent.

## `tasks/`

The `tasks` folder contains individual task files.

Example:

```text
tasks/task_01.json
```

## `tools/`

The `tools` folder contains example tool definitions.

Example:

```text
tools/example_tool.json
```

### Generate a task prompt

Use `gen_prompt.py` to generate the full LLM prompt for a specific task from `tasks_description.json`.

The script takes the task number as an argument, reads the matching task from `tasks_description.json`, and prints the complete prompt.

Example:

```bash
python gen_prompt.py 10
