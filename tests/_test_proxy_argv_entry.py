# -*- coding: utf-8 -*-
"""内嵌调用入口：qoder_proxy.main(argv) 必须只按传入的 argv 解析。

    python tests/_test_proxy_argv_entry.py

事故背景（v1.0.14_R 发版前）：并入上游 v1.9.7/v1.9.8 时，合并把上游的
`args = ap.parse_args()` 与 fork 的 `args = ap.parse_args(argv)` 并成了**两行**。
第二行忽略传入的 argv、改读 sys.argv —— 桌面壳内嵌启动网关时，sys.argv 里带着
壳自己的 `--smoke-test` / `--smoke-gui`，argparse 直接 exit 2：

    Qoder2API-Hub.exe: error: unrecognized arguments: --smoke-test

网关线程当场死，冒烟只剩 `health=FAIL`，CI（bash -e）必红。同一处副作用还有：
内嵌调用传的 `--port` 被默认值 8790 覆盖。

本套件钉死三件事：
  1) main() 里只有一次参数解析，且用的是 argv；
  2) 行为上：sys.argv 里放未知参数时，main(argv) 仍按 argv 走（不被污染）；
  3) 桌面壳侧的冒烟入口与内嵌 argv 构造方式不被上游合并悄悄改掉。
"""
import argparse
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _suite_head import *          # noqa: F401,F402

P, A = bootstrap()
declare_suite(__file__, ["qoder_proxy.py", "desktop/qoder_desktop.py"])

SRC = io.open(os.path.join(ROOT, "qoder_proxy.py"), encoding="utf-8").read()
DESK = io.open(os.path.join(ROOT, "desktop", "qoder_desktop.py"),
               encoding="utf-8").read()

# ---------------------------------------------------------------- 1) 源码形态
main_src = SRC.split("\ndef main(argv=None):", 1)[-1]
parse_calls = [ln.strip() for ln in main_src.split("\n")
               if "ap.parse_args(" in ln and not ln.strip().startswith("#")]
check("main() 里只有一次参数解析", len(parse_calls) == 1, parse_calls)
check("唯一那次解析用的是传入的 argv",
      parse_calls and parse_calls[0] == "args = ap.parse_args(argv)",
      parse_calls)

# ---------------------------------------------------------------- 2) 行为：argv 不被 sys.argv 污染
_saved_argv = list(sys.argv)
try:
    sys.argv = ["Qoder2API-Hub.exe", "--smoke-test", "--port", "9321"]
    # (a) --help 走 argv 时 exit 0；读 sys.argv 时会因未知参数 exit 2
    code = None
    try:
        P.main(["--help"])
    except SystemExit as exc:
        code = exc.code
    check("main(argv) 按传入 argv 解析（不被 sys.argv 的未知参数打断）",
          code == 0, code)

    # (b) argparse 实际收到的参数表 = 内嵌调用方给的 list
    captured = {}

    class _Abort(Exception):
        pass

    _real_parse = argparse.ArgumentParser.parse_args

    def _spy(self, args=None, namespace=None):
        captured["argv"] = list(args) if args is not None else None
        raise _Abort()

    argparse.ArgumentParser.parse_args = _spy
    try:
        P.main(["--port", "9321", "--accounts-dir", os.environ["ACCOUNTS_DIR"]])
    except _Abort:
        pass
    finally:
        argparse.ArgumentParser.parse_args = _real_parse
    check("argparse 收到的就是内嵌调用方传的 argv",
          captured.get("argv") == ["--port", "9321", "--accounts-dir",
                                   os.environ["ACCOUNTS_DIR"]],
          captured.get("argv"))
    check("内嵌 argv 未被 sys.argv 污染（没有 --smoke-test）",
          "--smoke-test" not in (captured.get("argv") or []),
          captured.get("argv"))
finally:
    sys.argv = _saved_argv

# ---------------------------------------------------------------- 3) 桌面壳侧
check("桌面壳认得 --smoke-test", '"--smoke-test"' in DESK)
check("桌面壳认得 --smoke-gui", '"--smoke-gui"' in DESK)
_gw = DESK.split("def start(self, host, port, lan):", 1)
check("Gateway.start 存在", len(_gw) == 2)
if len(_gw) == 2:
    _body = _gw[1].split("def stop(", 1)[0]
    check("Gateway.start 内嵌启动不透传 sys.argv（否则壳参数会灌进网关解析）",
          "sys.argv" not in _body, [ln.strip() for ln in _body.split("\n")
                                    if "sys.argv" in ln][:3])
    check("Gateway.start 显式传 --port（内嵌端口不被默认值 8790 覆盖）",
          '"--port"' in _body)

finish()
