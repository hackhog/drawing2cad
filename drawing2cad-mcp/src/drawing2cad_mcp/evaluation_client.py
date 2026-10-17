"""Replay declared MCP calls and retain the complete evaluation trace.

This client does not construct CAD or read drawing content itself. A plan names
the server command, tool calls, and evaluation metadata. All drawing and CAD
operations use the MCP session.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import traceback

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2)


def _resolve(value, directory):
    if isinstance(value, dict):
        if set(value) == {"$json_file"}:
            path = (directory / value["$json_file"]).resolve(strict=True)
            if path.stat().st_size > 2 * 1024 * 1024:
                raise ValueError("A JSON input exceeds 2 MiB.")
            return json.loads(path.read_text(encoding="utf-8-sig"))
        return {key: _resolve(item, directory) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve(item, directory) for item in value]
    return value


async def replay(plan_path: Path, output: Path):
    """Use a real stdio MCP connection. Keep each request and response intact."""
    plan_bytes = plan_path.read_bytes()
    if len(plan_bytes) > 4 * 1024 * 1024:
        raise ValueError("The replay plan exceeds 4 MiB.")
    plan = json.loads(plan_bytes.decode("utf-8-sig"))
    calls = plan["calls"]
    budget = plan.get("step_budget", 45)
    if not 1 <= budget <= 100 or not isinstance(calls, list) or len(calls) > budget:
        raise ValueError("The plan exceeds its tool-call budget.")
    output.mkdir(parents=True, exist_ok=False)
    (output / "plan.json").write_bytes(plan_bytes)
    summary = {"schema_version": 1, "plan_sha256": hashlib.sha256(plan_bytes).hexdigest(),
               "metadata": plan.get("metadata", {}), "questions": plan.get("questions", []),
               "step_budget": budget, "calls": [], "status": "running"}
    server = StdioServerParameters(**plan["server"])
    started = time.monotonic()
    try:
        with (output / "server-stderr.log").open("w", encoding="utf-8") as errors:
            async with stdio_client(server, errlog=errors) as streams:
                async with ClientSession(*streams, read_timeout_seconds=plan.get("call_timeout_seconds", 240)) as session:
                    initialized = await session.initialize()
                    (output / "initialize.json").write_text(_json(initialized.model_dump(mode="json", by_alias=True)), encoding="utf-8")
                    catalog = await session.list_tools()
                    (output / "catalog.json").write_text(_json(catalog.model_dump(mode="json", by_alias=True)), encoding="utf-8")
                    for index, call in enumerate(calls, 1):
                        arguments = _resolve(call.get("arguments", {}), plan_path.parent)
                        event = {"sequence": index, "started_at": datetime.now(timezone.utc).isoformat(),
                                 "name": call["name"], "arguments": arguments}
                        request_path = output / f"{index:03d}-request.json"
                        request_path.write_text(_json(event), encoding="utf-8")
                        before = time.monotonic()
                        try:
                            result = await session.call_tool(call["name"], arguments)
                            event["duration_seconds"] = time.monotonic() - before
                            event["response"] = result.model_dump(mode="json", by_alias=True)
                            event["status"] = "fail" if result.is_error else "pass"
                            response_path = output / f"{index:03d}-response.json"
                            response_path.write_text(_json(event), encoding="utf-8")
                            summary["calls"].append({"sequence": index, "name": call["name"], "status": event["status"],
                                                     "duration_seconds": event["duration_seconds"],
                                                     "request_sha256": hashlib.sha256(request_path.read_bytes()).hexdigest(),
                                                     "response_sha256": hashlib.sha256(response_path.read_bytes()).hexdigest()})
                        except Exception as error:
                            event.update(status="fail", error={"type": type(error).__name__, "message": str(error)})
                            summary["calls"].append(event)
                            raise
                        finally:
                            with (output / "trace.jsonl").open("a", encoding="utf-8") as trace:
                                trace.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
                        if event["status"] == "fail" and plan.get("stop_on_error", True):
                            break
        summary["status"] = "pass" if len(summary["calls"]) == len(calls) and all(item["status"] == "pass" for item in summary["calls"]) else "fail"
    except Exception as error:
        summary.update(status="fail", error={"type": type(error).__name__, "message": str(error)})
        (output / "client-error.log").write_text("".join(traceback.format_exception(error)), encoding="utf-8")
    finally:
        summary["duration_seconds"] = time.monotonic() - started
        summary["scope"] = "MCP call completion only. Model accuracy and acceptance require the recorded review and validation checks."
        (output / "summary.json").write_text(_json(summary), encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description="Replay an evaluation plan through MCP and record complete calls.")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(replay(args.plan.resolve(strict=True), args.output.resolve()))
    print(_json(result))
    raise SystemExit(0 if result["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
