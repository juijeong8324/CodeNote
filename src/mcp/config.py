import os


def github_mcp_config() -> dict:
    return {
        "type": "http",                          
        "url": "https://api.githubcopilot.com/mcp",   # GitHub 공식 Remote MCP 엔드포인트
        "headers": {
            "Authorization": f"Bearer {os.getenv('GITHUB_TOKEN')}",
            "Content-Type": "application/json"
        },
        "name": "github",
        # "timeout": 60,
    }