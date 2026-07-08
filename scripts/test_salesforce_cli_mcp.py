"""
Sanity check: spawns the official Salesforce CLI MCP server via stdio and
lists its available tools, confirming the server starts and speaks MCP
correctly before wiring it into Pulse's brief generation.
"""
import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    server_params = StdioServerParameters(
        command="npx",
        args=["-y", "@salesforce/mcp", "--orgs", "pulse-org", "--toolsets", "data"],
    )

    print("Starting Salesforce MCP server (this may take a moment on first run)...")

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("Session initialized.\n")

            tools = await session.list_tools()
            print(f"Available tools ({len(tools.tools)}):")
            for t in tools.tools:
                print(f"  - {t.name}: {t.description[:80] if t.description else ''}")

            soql_tool = next((t for t in tools.tools if "soql" in t.name.lower()), None)
            if soql_tool:
                print(f"\nFull input schema for {soql_tool.name}:")
                import json as _json
                print(_json.dumps(soql_tool.inputSchema, indent=2))

                print(f"\nCalling {soql_tool.name}...")
                result = await session.call_tool(
                    soql_tool.name,
                    arguments={
                        "query": "SELECT Name, Industry, AnnualRevenue FROM Account WHERE Name = 'Edge Communications'",
                        "usernameOrAlias": "pulse-org",
                        "directory": r"C:\Users\tirth\pulse",
                    },
                )
                for block in result.content:
                    if hasattr(block, "text"):
                        print(block.text[:1000])
            else:
                print("\nNo SOQL tool found — check tool names above.")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())
