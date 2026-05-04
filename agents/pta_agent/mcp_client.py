from __future__ import annotations

import sys
from pathlib import Path
from types import TracebackType
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from .json_utils import normalize_mcp_content


class McpClient:
    def __init__(self, server_script: Path):
        self.server_script = server_script
        self._stdio_cm: Any = None
        self._session_cm: Any = None
        self._session: ClientSession | None = None

    async def __aenter__(self) -> "McpClient":
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(self.server_script)],
            cwd=str(self.server_script.parent),
            encoding="utf-8",
            encoding_error_handler="replace",
        )
        self._stdio_cm = stdio_client(params)
        read_stream, write_stream = await self._stdio_cm.__aenter__()
        self._session_cm = ClientSession(read_stream, write_stream)
        self._session = await self._session_cm.__aenter__()
        await self._session.initialize()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._session_cm is not None:
            await self._session_cm.__aexit__(exc_type, exc, tb)
        if self._stdio_cm is not None:
            await self._stdio_cm.__aexit__(exc_type, exc, tb)

    async def list_resources(self) -> list[str]:
        assert self._session is not None
        result = await self._session.list_resources()
        return [str(resource.uri) for resource in result.resources]

    async def list_tools(self) -> list[str]:
        assert self._session is not None
        result = await self._session.list_tools()
        return [tool.name for tool in result.tools]

    async def list_tool_schemas(self) -> list[dict[str, Any]]:
        assert self._session is not None
        result = await self._session.list_tools()
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema,
            }
            for tool in result.tools
        ]

    async def read_resource(self, uri: str) -> Any:
        assert self._session is not None
        result = await self._session.read_resource(uri)
        return normalize_mcp_content(result)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        assert self._session is not None
        result = await self._session.call_tool(name, arguments)
        return normalize_mcp_content(result)
