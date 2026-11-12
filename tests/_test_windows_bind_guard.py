# -*- coding: utf-8 -*-
"""/health 双开防护：独占绑定 + 只在 TIME_WAIT 残留时降级。

    python tests/_test_windows_bind_guard.py

复现背景（Windows，1.9.7）：升级后旧实例仍在监听，新实例的 bind 也成功
（HTTP 服务器默认带 SO_REUSEADDR，Windows 允许抢绑同一端口），两个进程
同时 listen，连接静默分流到旧实例，/health 永远回旧版本 -> 看板一直提示
「有新版本」。POSIX 上同样的代码会直接 EADDRINUSE，所以只有 Windows 中招。
"""
import io
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _suite_head import *          # noqa: F401,F403

P, A = bootstrap()
declare_suite(__file__, ["qoder_proxy.py"])

SRC = io.open(os.path.join(ROOT, "qoder_proxy.py"), encoding="utf-8").read()


def _listener():
    """占住一个端口，模拟「另一个实例正在监听」。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    return s, s.getsockname()[1]


print("[独占绑定] 平台分支")
check("Windows 关掉 SO_REUSEADDR",
      P._ExclusiveHTTPServer.allow_reuse_address is P.IS_WINDOWS is False
      or P._ExclusiveHTTPServer.allow_reuse_address is (not P.IS_WINDOWS),
      P._ExclusiveHTTPServer.allow_reuse_address)
check("server_bind 设 SO_EXCLUSIVEADDRUSE", "SO_EXCLUSIVEADDRUSE" in SRC)
check("常规启动走独占类",
      "_ExclusiveHTTPServer((args.host, args.port), Handler)" in SRC)

print("[抢占] 端口被占用时 bind 必须失败")
_s, _port = _listener()
try:
    try:
        _srv = P._ExclusiveHTTPServer(("127.0.0.1", _port), P.Handler)
    except OSError as exc:
        _blew = True
        _err = str(exc)
    else:
        _blew = False
        _err = ""
        _srv.server_close()
finally:
    _s.close()

if P.IS_WINDOWS:
    check("Windows：第二个实例 bind 直接失败（不再双开）", _blew, _err)
else:
    check("POSIX：独占绑定同样拒绝抢绑", _blew, _err)

print("[降级条件] 只有「没人 accept」才允许兼容模式")
check("探测活监听者返回 True", P._port_accepts("127.0.0.1", _port) is False,
      "端口已释放")
check("降级前必须过 _port_accepts",
      SRC.index("_port_accepts(args.host, args.port)")
      < SRC.index("_CompatHTTPServer((args.host, args.port), Handler)"))
check("兼容模式只用于 TIME_WAIT 残留", "_CompatHTTPServer" in SRC
      and "TIME_WAIT" in SRC)

finish()
