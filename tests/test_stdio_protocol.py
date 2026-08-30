"""stdio 传输层协议合规测试（1.1.0 新增，防 P0 回归）

MCP 标准 stdio = 换行分隔 JSON（每行一条 JSON-RPC 消息）。
v1.0.x 曾误用 LSP 式 Content-Length 帧，导致任何标准 MCP 客户端都连不上——
本测试确保该类协议级回归在发布前被拦下。
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _server_env() -> dict:
    """子进程用独立临时库，绝不触碰用户真实记忆库。"""
    env = dict(os.environ)
    tmp = Path(tempfile.mkdtemp(prefix="wanyi_stdio_"))
    env["万忆中枢_MEMORY_DB"] = str(tmp / "test.db")
    env["万忆中枢_STORE_DIR"] = str(tmp / "store")
    env["OBSIDIAN_VAULT"] = ""
    return env


def _spawn():
    return subprocess.Popen(
        [sys.executable, "-u", "-m", "wanyi.memory_core"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        cwd=str(REPO_ROOT),
        env=_server_env(),
    )


def _send(proc, payload: dict) -> None:
    proc.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
    proc.stdin.flush()


def _recv(proc) -> dict:
    line = proc.stdout.readline()
    assert line, "服务器无响应（stdio 协议不兼容？）"
    return json.loads(line.decode("utf-8"))


def _rpc(proc, payload: dict) -> dict:
    _send(proc, payload)
    return _recv(proc)


@pytest.fixture(scope="module")
def server():
    proc = _spawn()
    yield proc
    proc.kill()


def test_initialize_newline_json(server):
    """MCP 标准握手：裸 JSON 行必须能收到响应（v1.0.x 在此挂掉）。"""
    resp = _rpc(server, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert resp["id"] == 1
    assert resp["result"]["protocolVersion"]
    assert resp["result"]["serverInfo"]["name"]
    # 版本号必须来自 version.py 唯一真源
    import wanyi

    assert resp["result"]["serverInfo"]["version"] == wanyi.__version__


def test_tools_list_returns_23(server):
    resp = _rpc(server, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    tools = resp["result"]["tools"]
    assert len(tools) == 23
    names = {t["name"] for t in tools}
    assert "万忆召回记忆" in names and "万忆记录见闻" in names


def test_tools_call_roundtrip(server):
    """写入→召回 全链路走 stdio 协议。"""
    resp = _rpc(server, {
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "万忆记录见闻",
                   "arguments": {"content": "stdio协议回归冒烟 1.1.0", "mem_type": "fact"}},
    })
    assert "error" not in resp

    resp = _rpc(server, {
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "万忆召回记忆", "arguments": {"query": "stdio协议回归冒烟"}},
    })
    text = resp["result"]["content"][0]["text"]
    assert "stdio协议回归冒烟" in text


def test_notification_gets_no_response(server):
    """通知（无 id）不产生响应，下一条响应必须对应后续请求。"""
    _send(server, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    resp = _rpc(server, {"jsonrpc": "2.0", "id": 9, "method": "tools/list", "params": {}})
    assert resp["id"] == 9


def test_content_length_frame_backward_compat():
    """旧式 LSP Content-Length 帧仍可解析（向后兼容）。"""
    proc = _spawn()
    try:
        body = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            ensure_ascii=False,
        ).encode("utf-8")
        proc.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
        proc.stdin.flush()
        resp = _recv(proc)
        assert resp["id"] == 1 and "result" in resp
    finally:
        proc.kill()


def test_server_exits_on_stdin_eof():
    """stdin 关闭后服务器必须干净退出（1.1.0 修复的 EOF 忙循环回归守卫）。"""
    proc = _spawn()
    proc.stdin.close()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        pytest.fail("服务器在 stdin EOF 后 15s 未退出（EOF 死循环？）")
