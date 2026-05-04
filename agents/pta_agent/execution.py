from __future__ import annotations

import time

from .mcp_client import McpClient
from .models import ActionProposal
from .state import StateManager
from .trace import TraceLogger


class ExecutionLayer:
    def __init__(self, client: McpClient, logger: TraceLogger):
        self.client = client
        self.logger = logger

    async def read_resource(self, proposal: ActionProposal, state: StateManager) -> None:
        assert proposal.resource_uri is not None
        started = time.perf_counter()
        payload = await self.client.read_resource(proposal.resource_uri)
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        state.add_resource(proposal.resource_uri, payload)
        self.logger.log(
            "resource_read",
            {"resource_uri": proposal.resource_uri, "latency_ms": latency_ms, "payload": payload},
        )

    async def call_tool(self, proposal: ActionProposal, state: StateManager) -> None:
        assert proposal.tool_name is not None
        started = time.perf_counter()
        result = await self.client.call_tool(proposal.tool_name, proposal.arguments)
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        state.add_tool_result(proposal.tool_name, proposal.arguments, result)
        self.logger.log(
            "tool_call",
            {"tool_name": proposal.tool_name, "arguments": proposal.arguments, "latency_ms": latency_ms, "result": result},
        )
