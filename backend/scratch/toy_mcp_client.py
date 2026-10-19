"""Phase 0.4 — MCP client 'hello world'.

Talks to a well-behaved reference server (NOT DVMCP yet) to prove baseline
client code before wrapping it. This exact ClientSession shape is what
``src/mcp_gateway/client_wrapper.py`` formalizes in Phase 2.

Requires Node (npx) for the reference server:
    npx -y @modelcontextprotocol/server-everything
"""
import asyncio

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    params = StdioServerParameters(
        command="npx", args=["-y", "@modelcontextprotocol/server-everything"]
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("Tools:", [t.name for t in tools.tools])
            if tools.tools:
                result = await session.call_tool(tools.tools[0].name, {})
                print("Result:", result)


if __name__ == "__main__":
    asyncio.run(main())
