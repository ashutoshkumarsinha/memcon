"""JSON-RPC 2.0 ACP client for kiro-cli (Agent Client Protocol)."""

from __future__ import annotations

import json
import os
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class PromptResult:
    text: str = ""
    stop_reason: str = ""
    kiro_context_pct: float = 0.0
    kiro_credits: float = 0.0
    tool_calls: list = field(default_factory=list)


class KiroACPClient:
    """Minimal stdlib ACP client for kiro-cli subprocess communication."""

    def __init__(
        self,
        cli_path: str = "kiro-cli",
        cwd: str | None = None,
        timeout_seconds: int = 600,
        auto_approve_tools: bool = True,
        on_chunk: Callable[[str], None] | None = None,
    ) -> None:
        self._cli_path = cli_path
        self._cwd = cwd or os.getcwd()
        self._timeout_seconds = timeout_seconds
        self._auto_approve_tools = auto_approve_tools
        self._on_chunk = on_chunk or (lambda _text: None)
        self._proc: subprocess.Popen[bytes] | None = None
        self._req_id = 0
        self._lock = threading.Lock()
        self._pending: dict[int, tuple[threading.Event, list[Any]]] = {}
        self._session_updates: dict[str, list[dict[str, Any]]] = {}
        self._session_metadata: dict[str, dict[str, Any]] = {}
        self._running = False

    def __enter__(self) -> KiroACPClient:
        self.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.stop()

    def start(self) -> dict[str, Any]:
        env = os.environ.copy()
        self._proc = subprocess.Popen(
            [self._cli_path, "acp"],
            cwd=self._cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            bufsize=0,
        )
        self._running = True
        threading.Thread(target=self._read_loop, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        return self._send_request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": True, "writeTextFile": True},
                    "terminal": True,
                },
                "clientInfo": {"name": "memcon", "version": "1.0"},
            },
        )

    def stop(self) -> None:
        self._running = False
        if self._proc and self._proc.poll() is None:
            if self._proc.stdin:
                self._proc.stdin.close()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    def session_new(self) -> str:
        result = self._send_request(
            "session/new",
            {"cwd": self._cwd, "mcpServers": []},
        )
        session_id = result.get("sessionId", "")
        if not session_id:
            raise RuntimeError(f"kiro session/new returned no sessionId: {result}")
        return session_id

    def session_set_model(self, session_id: str, model: str) -> None:
        self._send_request(
            "session/set_model",
            {"sessionId": session_id, "model": model},
        )

    def session_prompt(self, session_id: str, text: str) -> PromptResult:
        self._session_updates[session_id] = []
        result = self._send_request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": text}],
            },
            timeout=self._timeout_seconds,
        )
        return self._build_prompt_result(session_id, result)

    def _next_id(self) -> int:
        with self._lock:
            self._req_id += 1
            return self._req_id

    def _send_request(
        self,
        method: str,
        params: dict[str, Any],
        timeout: float | None = None,
    ) -> dict[str, Any]:
        if not self._proc or not self._proc.stdin:
            raise RuntimeError("kiro-cli ACP process is not running")
        req_id = self._next_id()
        msg = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        evt = threading.Event()
        holder: list[Any] = []
        self._pending[req_id] = (evt, holder)
        self._proc.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode())
        self._proc.stdin.flush()
        wait_for = self._timeout_seconds if timeout is None else timeout
        if not evt.wait(timeout=wait_for):
            self._pending.pop(req_id, None)
            raise TimeoutError(f"kiro {method} timed out after {wait_for}s")
        self._pending.pop(req_id, None)
        if len(holder) == 2 and holder[0] is None:
            error = holder[1]
            raise RuntimeError(
                f"kiro RPC error {error.get('code')}: {error.get('message')}"
            )
        return holder[0] if holder else {}

    def _read_loop(self) -> None:
        while self._running and self._proc and self._proc.stdout:
            try:
                line = self._proc.stdout.readline(4 * 1024 * 1024)
                if not line:
                    break
                self._handle_line(line.decode(errors="replace").strip())
            except Exception:
                if self._running:
                    raise
                break

    def _read_stderr(self) -> None:
        while self._running and self._proc and self._proc.stderr:
            line = self._proc.stderr.readline()
            if not line:
                break

    def _handle_line(self, line: str) -> None:
        if not line:
            return
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return

        msg_id = msg.get("id")
        method = msg.get("method")

        if msg_id is not None and method is None:
            pending = self._pending.get(msg_id)
            if pending:
                evt, holder = pending
                if msg.get("error"):
                    holder.extend([None, msg["error"]])
                else:
                    holder.append(msg.get("result", {}))
                evt.set()
            return

        if msg_id is not None and method == "session/request_permission":
            option_id = "allow_once" if self._auto_approve_tools else "deny"
            self._send_permission_response(msg_id, msg.get("params", {}), option_id)
            return

        if method and msg_id is None:
            params = msg.get("params", {})
            session_id = params.get("sessionId", "")
            if method == "session/update" and session_id:
                update = params.get("update", {})
                updates = self._session_updates.get(session_id)
                if updates is not None:
                    updates.append(update)
                if update.get("sessionUpdate") == "agent_message_chunk":
                    content = update.get("content", {})
                    if isinstance(content, dict) and content.get("type") == "text":
                        chunk = content.get("text", "")
                        if chunk:
                            self._on_chunk(chunk)
            elif method == "_kiro.dev/metadata" and session_id:
                meta = self._session_metadata.get(session_id, {})
                meta.update(params)
                self._session_metadata[session_id] = meta

    def _send_permission_response(
        self,
        msg_id: int,
        params: dict[str, Any],
        option_id: str,
    ) -> None:
        if not self._proc or not self._proc.stdin:
            return
        outcome = (
            {"outcome": "cancelled"}
            if option_id == "deny"
            else {"outcome": "selected", "optionId": option_id}
        )
        response = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"outcome": outcome},
        }
        self._proc.stdin.write((json.dumps(response) + "\n").encode())
        self._proc.stdin.flush()

    def _build_prompt_result(
        self,
        session_id: str,
        rpc_result: dict[str, Any],
    ) -> PromptResult:
        updates = self._session_updates.pop(session_id, [])
        meta = self._session_metadata.get(session_id, {})
        text_parts: list[str] = []
        for update in updates:
            if update.get("sessionUpdate") != "agent_message_chunk":
                continue
            content = update.get("content", {})
            if isinstance(content, dict) and content.get("type") == "text":
                text_parts.append(content.get("text", ""))
        return PromptResult(
            text="".join(text_parts),
            stop_reason=str(rpc_result.get("stopReason", "")),
            kiro_context_pct=float(meta.get("contextUsagePercentage", 0.0)),
            kiro_credits=float(meta.get("credits", 0.0)),
        )
