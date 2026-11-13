# -*- coding: utf-8 -*-
"""一键更新整块未采纳（fork 红线）——等价于上游 #154 的「查不到 GitHub 不谎报」。

    python tests/_test_update_lookup_failed.py

上游 PR #154 修的是 `/update/plan` 在 GitHub 匿名限流（403）时把 latest 落成空串、
于是面板一边显示「当前已是最新版本」一边显示「发现新版本」。那个修复点落在
`update_plan_info()` —— 但**本 fork 自 v1.0.6_R 起整块剔除了该功能**
（qoder_updater.py / /update/plan / /update/apply / 看板「一键更新」按钮）：
内嵌网关自拉上游 tarball 会把 fork 的文件换成上游原版，桌面发行版的更新通道
是 Inno 安装包。

因此本套件不再是上游那条用例的复刻，而是**红线守卫 + fork 形态下的等价落点**：
  1) 一键更新相关的模块/路由/定义必须都不存在（防止随上游合并回流）；
  2) fork 自己保留的只读检查（/update/check，面板「检查更新」）在 GitHub
     不可达时必须**如实报错误**，而不是谎报「已是最新版本」——这是上游修复的
     精神在 fork 形态下的落点。
"""
import io
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _suite_head import *          # noqa: F401,F402

P, A = bootstrap()
declare_suite(__file__, ["qoder_proxy.py"])

SRC = io.open(os.path.join(ROOT, "qoder_proxy.py"), encoding="utf-8").read()

# ---------------------------------------------------------------- 红线守卫
check("qoder_updater 模块不存在（fork 整块剔除）",
      not hasattr(P, "qoder_updater"))
check("无 /update/plan 路由（上游整块未采纳）",
      'if path == "/update/plan":' not in SRC)
check("无 /update/apply 路由（上游整块未采纳）",
      'if path == "/update/apply":' not in SRC)
check("无 update_plan_info / apply_update_now 定义",
      "def update_plan_info(" not in SRC and "def apply_update_now(" not in SRC)


# ---------------------------------------------------------------- 只读检查语义
class _RateLimited(object):
    """模拟 GitHub 匿名限流（403）。"""

    def __call__(self, req, timeout=None):
        import urllib.error
        raise urllib.error.HTTPError("https://api.github.com/", 403,
                                     "rate limit exceeded", {}, None)


# fork：出站统一走 UPSTREAM_OPENER（patch P.urllib.request.urlopen 拦不到——
# 第 6 次同型），故从 fork 的测试注入点 UpstreamOpener._stub 制造限流。
_orig_stub = A.UpstreamOpener._stub
try:
    # 1) 无缓存 + 限流：必须 ok=False + 有 error，不许谎报「已是最新版本」
    P._update_cache.update({"at": 0.0, "data": None})
    A.UpstreamOpener._stub = _RateLimited()
    info = P.check_for_update(force=True)
    check("GitHub 不可达时不谎报「已是最新版本」",
          not (info.get("ok") is True and info.get("has_update") is False
               and not info.get("error")),
          info)
    check("不可达时 ok=False 且给出可读错误（用户知道是网络/限流）",
          info.get("ok") is False and bool(info.get("error")), info)
    check("不可达时不编造版本号（latest 为空）",
          not info.get("latest"), info)

    # 2) 有成功缓存 + 限流：沿用缓存结论（面板左边那一列的来源），不重复打 API
    P._update_cache.update({
        "at": time.time(),
        "data": {"ok": True, "current": P.VERSION, "latest": "v99.0.0",
                 "has_update": True, "url": "", "published_at": "",
                 "name": "", "checked_at": 0, "error": ""},
    })
    cached = P.check_for_update()
    check("有缓存时限流沿用缓存结论（不因本次 403 反复自相矛盾）",
          cached.get("latest") == "v99.0.0" and cached.get("ok") is True,
          cached)
finally:
    A.UpstreamOpener._stub = _orig_stub
    P._update_cache.update({"at": 0.0, "data": None})

finish()
