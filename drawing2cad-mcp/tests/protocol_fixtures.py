"""Harmless stdio protocol fixtures for MCP client tests."""

# This fixture tests JSON-RPC transport. It performs no PDF or CAD operation.
UPSTREAM = r'''
import json, sys
tool = {
    "name": "echo", "title": "Echo title", "description": "Full tool metadata",
    "inputSchema": {"type": "object", "properties": {"value": {"type": "string"}}},
    "outputSchema": {"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
    "annotations": {"readOnlyHint": True, "openWorldHint": False},
    "icons": [{"src": "data:image/png;base64,aA==", "mimeType": "image/png"}],
    "_meta": {"custom": {"preserve": 7}}
}
for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    method = request["method"]
    params = request.get("params", {})
    if method == "initialize":
        result = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "protocol-fixture", "version": "1.0"}}
    elif method == "tools/list":
        result = {"tools": [tool]}
    elif method == "tools/call":
        value = params.get("arguments", {}).get("value", "same")
        result = {
            "content": [{"type": "text", "text": value},
                        {"type": "image", "data": "aGVsbG8=", "mimeType": "image/png"},
                        {"type": "resource", "resource": {"uri": "fixture://result", "text": "preserved"}}],
            "structuredContent": {"value": value}, "isError": False,
            "_meta": {"marker": 42}
        }
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
'''
