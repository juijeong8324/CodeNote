import os


def github_mcp_config() -> dict:
    return {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "transport": "stdio",
        "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": os.environ["GITHUB_TOKEN"]},
    }


def notion_mcp_config() -> dict:
    return {
        "command": "npx",
        "args": ["-y", "@notionhq/notion-mcp-server"],
        "transport": "stdio",
        "env": {"NOTION_API_KEY": os.environ["NOTION_API_KEY"]},
    }
