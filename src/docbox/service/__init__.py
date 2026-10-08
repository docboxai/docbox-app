"""Plain-Python operations behind every DocBox front end: the HTTP routes the desktop app
calls, the `docbox` CLI and the MCP server. Nothing here imports FastAPI; failures are
ServiceErrors (service/errors.py) that each front end turns into its own kind of error."""
