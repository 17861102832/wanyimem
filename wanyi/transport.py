"""万忆中枢 stdio 传输层（transport）
MCP 标准 stdio：换行分隔 JSON（每行一条 JSON-RPC 消息）。
兼容读取旧式 LSP Content-Length 帧（首行为 content-length 头时按帧解析）。
1.1.0 起自 memory_core 拆分；入口：`python -m wanyi` / `python -m wanyi.memory_core`。
"""
import sys

try:  # 包内导入（wanyi.transport）
    from .engine import handle_request
except ImportError:  # 顶层导入（sys.path hack 双模兼容）
    from engine import handle_request


def _read_exact(n: int) -> bytes:
    """从stdin精确读取n字节"""
    data = b""
    while len(data) < n:
        chunk = sys.stdin.buffer.read(n - len(data))
        if not chunk:
            raise EOFError()
        data += chunk
    return data


def _read_message() -> dict | None:
    """读取一条MCP消息（MCP标准 stdio：换行分隔JSON；兼容旧式Content-Length帧）。

    stdin 关闭（EOF）时抛 EOFError，由 main() 捕获退出；
    绝不能把 EOF 当 None 返回——那会让主循环空转烧 CPU（1.1.0 修复）。
    """
    import json as _json
    raw = sys.stdin.buffer.readline()
    if not raw:
        raise EOFError()
    line = raw.decode("utf-8", errors="replace").strip()
    if not line:
        return None
    # 兼容旧式 LSP Content-Length 帧：首行即 content-length 头时按帧读取
    if line.lower().startswith("content-length:"):
        try:
            content_length = int(line.split(":", 1)[1].strip())
        except ValueError:
            return None
        # 跳过剩余头部直到空行
        while True:
            h = sys.stdin.buffer.readline()
            if not h or h.decode("utf-8", "replace").strip() == "":
                break
        body = _read_exact(content_length)
        try:
            return _json.loads(body.decode("utf-8"))
        except _json.JSONDecodeError:
            return None
    # 标准路径：整行即一条 JSON-RPC 消息
    try:
        return _json.loads(line)
    except _json.JSONDecodeError:
        return None


def _write_message(msg: dict):
    """写入一条MCP消息（MCP标准 stdio：换行分隔JSON）"""
    import json as _json
    body = _json.dumps(msg, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(body + b"\n")
    sys.stdout.buffer.flush()


def main():
    """标准MCP stdio传输层（换行分隔JSON）"""
    # 通知类型的方法（不需要响应）
    NOTIFICATION_METHODS = {
        "notifications/initialized",
        "notifications/cancelled",
        "$/cancelRequest",
    }
    while True:
        try:
            req = _read_message()
        except EOFError:
            break
        if req is None:
            continue
        # 通知（无id）不需要响应
        if isinstance(req, dict) and "id" not in req:
            method = req.get("method", "")
            if method not in NOTIFICATION_METHODS:
                # 处理非标准通知（但不响应）
                pass
            continue
        if isinstance(req, list):
            # 批量请求
            responses = []
            for r in req:
                if "id" in r:
                    resp = handle_request(r)
                    responses.append(resp)
            for resp in responses:
                _write_message(resp)
        else:
            resp = handle_request(req)
            if resp is not None:
                _write_message(resp)

if __name__ == "__main__":
    main()
