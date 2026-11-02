# Use Brainamon as a local MCP server

Install the source dependencies using [BUILDING.md](BUILDING.md). Configure an
MCP client to start the checkout's Python interpreter with `-m mcp_local`, with
the checkout as its working directory. For example, replace these placeholder
paths with your checkout and virtual environment:

```json
{
  "mcpServers": {
    "brainamon": {
      "command": "C:\\work\\brainamon\\.venv\\Scripts\\python.exe",
      "args": ["-m", "mcp_local"],
      "cwd": "C:\\work\\brainamon"
    }
  }
}
```

Use the same BRAINAMON_HOME and CM_DATA_DIR as your running app when supplying
explicit runtime paths. The client configuration is local; it is not supplied
with somebody else's absolute paths or credentials.

Read tools work with Brainamon closed. Jobs such as Describe, Categorize and
Fetch link info need the app running. A job or a note write waits for your click
inside Brainamon unless you turn on **Run requests without asking** in Settings.
Approving the server in an MCP client does not approve these app requests.
Automatic requests can replace a personal note or run AI jobs that your provider
charges for. The MCP server is local, has no delete tool, and sends writes through
the running app's request flow.
