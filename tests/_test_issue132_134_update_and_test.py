"""#132 一键更新按钮按 can_apply 门控 + #134 账号测试探活与提示。"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _suite_head import *          # noqa: F401,F403

P, A = bootstrap()
declare_suite(__file__, ["qoder_proxy.py", "dashboard.html"])
import qoder_catalog as C          # noqa: E402

_src = io.open(os.path.join(ROOT, "qoder_proxy.py"), encoding="utf-8").read()
_dash = io.open(os.path.join(ROOT, "dashboard.html"), encoding="utf-8").read()

print("[#132] fork 红线：一键更新整块剔除（桌面版更新走 Inno 安装包）")
# 上游 #132 给 /update/plan 加 can_apply 门控、看板按它渲染按钮；本 fork 自
# v1.0.6_R 起整块剔除该功能（qoder_updater / /update/plan / /update/apply /
# 看板按钮——内嵌网关自拉上游 tarball 会把 fork 文件换成上游原版）。合并时
# 这两处曾随 auto-merge 回流，已在缝合时再次剔除；这里改断言为红线守卫：
# 不是「门控语义正确」，而是「功能根本不存在」。
check("/update/plan 路由不存在（红线）",
      'if path == "/update/plan":' not in _src)
check("/update/apply 路由不存在（红线）",
      'if path == "/update/apply":' not in _src)
check("update_plan_info/apply_update_now 定义不存在（红线）",
      "def update_plan_info(" not in _src and "def apply_update_now(" not in _src)
check("看板无一键更新按钮与 /update/plan 预取（红线）",
      "applyUpdate" not in _dash and "getJSON('/update/plan')" not in _dash)
check("看板更新区仍保留「检查更新 + 发布说明链接」（只读部分不是红线）",
      "loadUpdateState" in _dash and "发布说明" in _dash)

print("[#134] 测试默认用免费模型探活")
check("有 _default_test_model", "def _default_test_model(" in _src)
check("0 价优先（price_factor == 0）",
      'm.get("price_factor") == 0' in _src)
check("is_free 只作次选（它表示含免费权益，不等于 0 价）",
      'bool(m.get("is_free"))' in _src)
_cn = P._default_test_model("cn")
_intl = P._default_test_model("intl")
check("CN 默认探活模型是真免费模型", "Flash" in _cn or "flash" in _cn, _cn)
check("INTL 默认探活模型同样免费", "Flash" in _intl or "flash" in _intl, _intl)
_i2 = _src.index('if path == "/accounts/test":')
_seg2 = _src[_i2:_i2 + 2000]
check("测试入口用 _default_test_model 兜底", "_default_test_model(" in _seg2)
check("显式 model 仍以调用方为准",
      'payload.get("model")' in _seg2.split("_default_test_model(")[0])

print("[#134] 额度/排队类失败不再给账号叠冷却")
# fork 缝合形态：正向判定 test_quota_hit（quota 类为真），尾部 note_error 跳过
check("112/110/10605 被排除在 note_error 之外（fork 正向判定形态）",
      '"112" in _detail' in _src and '"10605" in _detail' in _src
      and "if not test_quota_hit:" in _src
      and "account.note_error(shown[:120], cooldown=60)" in _src)

print("[#134] 面板 toast 优先显示 hint")
check("hint 放前面", "const _head = r.hint ?" in _dash)
check("原文放括号里（仍可追查）",
      "'（' + (r.error || r.status || '异常') + '）'" in _dash)

finish()
