# MCP Benchmark Server

This directory contains the deterministic MCP server used by the benchmark.

## Run

```bash
uv run python main.py
```

## Contents

- `main.py`: MCP resource and tool definitions.
- `resource_data/`: JSON data exposed through MCP resources.
- `pyproject.toml` and `uv.lock`: server environment files.

The server is the source of truth for MCP tool names, descriptions, and argument schemas. Agents should discover tool schemas through MCP `list_tools()` rather than a separate static schema file.
