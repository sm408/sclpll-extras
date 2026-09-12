from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("pygls")


def _frame(payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


def _messages(output: bytes) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    remaining = output
    while remaining:
        header, separator, remaining = remaining.partition(b"\r\n\r\n")
        if not separator:
            break
        length = next(
            int(line.split(b":", 1)[1].strip())
            for line in header.split(b"\r\n")
            if line.lower().startswith(b"content-length:")
        )
        body, remaining = remaining[:length], remaining[length:]
        values.append(json.loads(body))
    return values


def test_stdio_server_initializes_publishes_diagnostics_and_completes(tmp_path: Path) -> None:
    uri = (tmp_path / "demo.sclpll").as_uri()
    source = "@workflow demo\n@var delay = 1\n@step wait\n  sleep @delay\n"
    (tmp_path / "workspace.sclpll").write_text(source, encoding="utf-8")
    payload = b"".join(
        [
            _frame(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "processId": None,
                        "rootUri": tmp_path.as_uri(),
                        "capabilities": {},
                        "workspaceFolders": [{"uri": tmp_path.as_uri(), "name": "test"}],
                    },
                }
            ),
            _frame({"jsonrpc": "2.0", "method": "initialized", "params": {}}),
            _frame(
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/didOpen",
                    "params": {
                        "textDocument": {
                            "uri": uri,
                            "languageId": "sclpll",
                            "version": 1,
                            "text": source,
                        }
                    },
                }
            ),
            _frame(
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/didChange",
                    "params": {
                        "textDocument": {"uri": uri, "version": 3},
                        "contentChanges": [{"text": source}],
                    },
                }
            ),
            _frame(
                {
                    "jsonrpc": "2.0",
                    "id": 11,
                    "method": "textDocument/codeLens",
                    "params": {"textDocument": {"uri": uri}},
                }
            ),
            _frame(
                {
                    "jsonrpc": "2.0",
                    "id": 12,
                    "method": "textDocument/foldingRange",
                    "params": {"textDocument": {"uri": uri}},
                }
            ),
            _frame(
                {
                    "jsonrpc": "2.0",
                    "id": 13,
                    "method": "workspace/symbol",
                    "params": {"query": "demo"},
                }
            ),
            _frame(
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/didChange",
                    "params": {
                        "textDocument": {"uri": uri, "version": 2},
                        "contentChanges": [{"text": "@workflow demo\n@ouput report:json\n"}],
                    },
                }
            ),
            _frame(
                {
                    "jsonrpc": "2.0",
                    "id": 14,
                    "method": "textDocument/codeAction",
                    "params": {
                        "textDocument": {"uri": uri},
                        "range": {
                            "start": {"line": 1, "character": 2},
                            "end": {"line": 1, "character": 2},
                        },
                        "context": {"diagnostics": []},
                    },
                }
            ),
            _frame(
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/didChange",
                    "params": {
                        "textDocument": {"uri": uri, "version": 4},
                        "contentChanges": [{"text": source}],
                    },
                }
            ),
            _frame(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "textDocument/completion",
                    "params": {
                        "textDocument": {"uri": uri},
                        "position": {"line": 3, "character": 2},
                    },
                }
            ),
            _frame(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "textDocument/hover",
                    "params": {
                        "textDocument": {"uri": uri},
                        "position": {"line": 3, "character": 3},
                    },
                }
            ),
            _frame(
                {
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "textDocument/signatureHelp",
                    "params": {
                        "textDocument": {"uri": uri},
                        "position": {"line": 3, "character": 7},
                    },
                }
            ),
            _frame(
                {
                    "jsonrpc": "2.0",
                    "id": 6,
                    "method": "textDocument/definition",
                    "params": {
                        "textDocument": {"uri": uri},
                        "position": {"line": 3, "character": 9},
                    },
                }
            ),
            _frame(
                {
                    "jsonrpc": "2.0",
                    "id": 7,
                    "method": "textDocument/rename",
                    "params": {
                        "textDocument": {"uri": uri},
                        "position": {"line": 3, "character": 9},
                        "newName": "pause",
                    },
                }
            ),
            _frame(
                {
                    "jsonrpc": "2.0",
                    "id": 8,
                    "method": "textDocument/documentSymbol",
                    "params": {"textDocument": {"uri": uri}},
                }
            ),
            _frame(
                {
                    "jsonrpc": "2.0",
                    "id": 9,
                    "method": "textDocument/semanticTokens/full",
                    "params": {"textDocument": {"uri": uri}},
                }
            ),
            _frame(
                {
                    "jsonrpc": "2.0",
                    "id": 10,
                    "method": "textDocument/formatting",
                    "params": {
                        "textDocument": {"uri": uri},
                        "options": {"tabSize": 2, "insertSpaces": True},
                    },
                }
            ),
            _frame({"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None}),
            _frame({"jsonrpc": "2.0", "method": "exit", "params": {}}),
        ]
    )
    completed = subprocess.run(
        [sys.executable, "-m", "sclpll_language_server", "--stdio"],
        input=payload,
        capture_output=True,
        check=False,
        timeout=20,
    )
    messages = _messages(completed.stdout)

    initialize = next(message for message in messages if message.get("id") == 1)
    assert "result" in initialize, messages
    assert "completionProvider" in initialize["result"]["capabilities"]
    completion = next(message for message in messages if message.get("id") == 2)
    assert "sleep" in {item["label"] for item in completion["result"]["items"]}
    hover = next(message for message in messages if message.get("id") == 4)
    assert "sleep(" in hover["result"]["contents"]["value"]
    signature = next(message for message in messages if message.get("id") == 5)
    assert signature["result"]["signatures"][0]["label"].startswith("sleep(")
    definition = next(message for message in messages if message.get("id") == 6)
    assert definition["result"]["range"]["start"]["line"] == 1
    rename = next(message for message in messages if message.get("id") == 7)
    assert rename["result"]["changes"][uri]
    symbols = next(message for message in messages if message.get("id") == 8)
    assert {item["name"] for item in symbols["result"]} >= {"demo", "delay", "wait"}
    semantic = next(message for message in messages if message.get("id") == 9)
    assert semantic["result"]["data"]
    assert len(semantic["result"]["data"]) >= 25  # declarations plus the @delay reference
    formatting = next(message for message in messages if message.get("id") == 10)
    assert formatting["result"][0]["newText"].startswith("@workflow demo")
    lenses = next(message for message in messages if message.get("id") == 11)
    assert {item["command"]["title"] for item in lenses["result"]} >= {"Run Workflow", "Validate"}
    folding = next(message for message in messages if message.get("id") == 12)
    assert folding["result"]
    workspace = next(message for message in messages if message.get("id") == 13)
    assert any(item["name"] == "demo" for item in workspace["result"])
    action = next(message for message in messages if message.get("id") == 14)
    quick_fix = next(item for item in action["result"] if item["title"] == "Change to output")
    assert quick_fix["edit"]["changes"][uri][0]["newText"] == "@output"
    assert any(item["title"] == "Format document" for item in action["result"])
    assert any(message.get("method") == "textDocument/publishDiagnostics" for message in messages)
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")


def test_stdio_server_respects_diagnostics_and_semantic_token_toggles(tmp_path: Path) -> None:
    uri = (tmp_path / "demo.sclpll").as_uri()
    source = "@workflow demo\n@ouput report:json\n"
    payload = b"".join(
        [
            _frame(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "processId": None,
                        "rootUri": tmp_path.as_uri(),
                        "capabilities": {},
                        "initializationOptions": {
                            "diagnostics": False,
                            "semanticHighlighting": False,
                        },
                    },
                }
            ),
            _frame({"jsonrpc": "2.0", "method": "initialized", "params": {}}),
            _frame(
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/didOpen",
                    "params": {
                        "textDocument": {
                            "uri": uri,
                            "languageId": "sclpll",
                            "version": 1,
                            "text": source,
                        }
                    },
                }
            ),
            _frame(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "textDocument/semanticTokens/full",
                    "params": {"textDocument": {"uri": uri}},
                }
            ),
            _frame({"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None}),
            _frame({"jsonrpc": "2.0", "method": "exit", "params": {}}),
        ]
    )
    completed = subprocess.run(
        [sys.executable, "-m", "sclpll_language_server", "--stdio"],
        input=payload,
        capture_output=True,
        check=False,
        timeout=20,
    )
    messages = _messages(completed.stdout)

    semantic = next(message for message in messages if message.get("id") == 2)
    assert semantic["result"]["data"] == []
    published = next(
        message
        for message in messages
        if message.get("method") == "textDocument/publishDiagnostics"
    )
    assert published["params"]["diagnostics"] == []
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
