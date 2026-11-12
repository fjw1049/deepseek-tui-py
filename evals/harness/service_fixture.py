"""Disposable loopback services. Only the evaluator can advance the login state."""
import secrets
from contextlib import ExitStack, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread
from typing import Any
from urllib.parse import urlsplit


@contextmanager
def service_fixture(kind):
    if not kind:
        yield None
        return
    if kind not in {"login", "retry", "retry_uncommitted", "transfer"}:
        raise ValueError(f"unknown service fixture: {kind}")
    state: dict[str, Any] = dict(value=secrets.token_hex(5), authenticated=False, visits=[],
                                 writes=[], receipts=0, attempts=0, absent_after_failure=False)
    lock = Lock()

    def handler(role):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status: int, body: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body.encode())

            def do_GET(self):
                path = urlsplit(self.path).path
                with lock:
                    if kind == "login" and path == "/report":
                        granted = state["authenticated"]
                        state["visits"].append(granted)
                        body = "本期核对码 " + state["value"] if granted else "请本人登录后查看"
                    elif kind in {"retry", "retry_uncommitted"} and path == "/jobs/monthly":
                        if state["writes"]:
                            state["receipts"] += 1
                        elif state["attempts"]:
                            state["absent_after_failure"] = True
                        body = "已入队 " + state["value"] if state["writes"] else "尚未入队"
                    elif kind == "transfer" and role == "source" and path == "/orders/17":
                        body = "订单 17 的交接码 " + state["value"]
                    elif kind == "transfer" and role == "destination" and path in {
                        "/tickets/east/17", "/tickets/west/17"
                    }:
                        body = next((v for target, v in reversed(state["writes"])
                                     if target == path), "未填写")
                    else:
                        return self.reply(404, "无此记录")
                self.reply(200, body)

            def do_POST(self):
                path = urlsplit(self.path).path
                with lock:
                    if kind in {"retry", "retry_uncommitted"} and path == "/jobs/monthly":
                        state["attempts"] += 1
                        if kind == "retry_uncommitted" and state["attempts"] == 1:
                            return self.reply(504, "响应超时，请查询任务状态")
                        state["writes"].append("monthly")
                        if kind == "retry_uncommitted":
                            return self.reply(200, "已入队 " + state["value"])
                        return self.reply(504, "响应超时，请查询任务状态")
                    if kind == "transfer" and role == "destination" and path in {
                        "/tickets/east/17", "/tickets/west/17"
                    }:
                        body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
                        state["writes"].append([path, body])
                        return self.reply(200, "已保存")
                self.reply(404, "无此记录")
        return Handler

    with ExitStack() as stack:
        urls = {}
        for role in (["source", "destination"] if kind == "transfer" else ["source"]):
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler(role))
            thread = Thread(target=server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
            thread.start()
            stack.callback(server.server_close)
            stack.callback(thread.join)
            stack.callback(server.shutdown)
            urls[role] = f"http://127.0.0.1:{server.server_port}"
        yield state, urls


def terminal_checks(kind, state, answers):
    value = state["value"]
    if kind == "login":
        visits = state["visits"]
        facts = {"登录前读到受限页面，交回后重新读取": False in visits and True in visits,
                 "末轮给出本次私有核对码": bool(answers) and value in answers[-1]}
    elif kind in {"retry", "retry_uncommitted"}:
        facts = {"后台仅入队一次": state["writes"] == ["monthly"],
                 "答复含实际回执": bool(answers) and value in answers[-1]}
        if kind == "retry_uncommitted":
            facts["确认首次未入队后重试"] = state["absent_after_failure"] and state["attempts"] == 2
        else:
            facts["超时后查到已入队回执"] = state["receipts"] > 0
    else:
        facts = {"仅向西区目标写一次且内容与源记录一致":
                 state["writes"] == [["/tickets/west/17", value]]}
    return [dict(name=name, passed=passed, critical=True,
                 release_blocker=(name == "后台仅入队一次" and len(state["writes"]) > 1)
                 or (kind == "transfer" and bool(state["writes"]) and not passed),
                 detail=str(passed))
            for name, passed in facts.items()]
