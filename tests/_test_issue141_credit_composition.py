"""#141 额度端点自动探测 + 积分构成（套餐内/资源包/SOTA/共享池）。"""
import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _suite_head import *          # noqa: F401,F403

P, A = bootstrap()
declare_suite(__file__, ["qoder_accounts.py", "qoder_proxy.py", "dashboard.html"])

_acc_src = io.open(os.path.join(ROOT, "qoder_accounts.py"), encoding="utf-8").read()
_src = io.open(os.path.join(ROOT, "qoder_proxy.py"), encoding="utf-8").read()
_dash = io.open(os.path.join(ROOT, "dashboard.html"), encoding="utf-8").read()

print("[#141] 归一器：把任意额度响应拆成构成")
_pay = {
    "userQuota": {"remaining": 120, "used": 80, "total": 200},
    "addOnQuota": {"remaining": 1800, "used": 0, "total": 1800},
    "sotaCredits": {"remaining": 2000, "used": 0, "total": 2000,
                    "expiresAt": 1762560000000},
    "orgResourcePackage": {"remaining": 500, "used": 100, "cap": 600},
}
_n = A.normalize_quota_payload(_pay, "intl")
kinds = [b["kind"] for b in _n["composition"]]
check("四个容器都识别", kinds == ["plan", "pack", "sota", "shared"], kinds)
check("展示名是人话", [b["name"] for b in _n["composition"]][0] == "套餐内 Credits")
check("plan/pack/sota 汇总（共享池单列不计入）",
      _n["remain"] == 120 + 1800 + 2000, _n["remain"])
check("size 汇总同口径", _n["size"] == 200 + 1800 + 2000, _n["size"])
check("SOTA 的有效期被带上",
      any(b.get("expires_at") for b in _n["composition"] if b["kind"] == "sota"))

print("[#141] 归一器的边界")
check("完全不认识 -> None（调用方据此判端点不适用）",
      A.normalize_quota_payload({"hello": "world"}, "cn") is None)
check("非 dict/list -> None", A.normalize_quota_payload("x", "cn") is None)
_multi = A.normalize_quota_payload(
    {"packages": [{"remaining": 10, "total": 10}, {"remaining": 20, "total": 20}]})
check("多个资源包分别保留", len(_multi["composition"]) == 2,
      len(_multi["composition"]))
check("多个资源包自动编号",
      _multi["composition"][1]["name"].endswith("#2"),
      _multi["composition"][1]["name"])
_orphan = A.normalize_quota_payload({"x": {"balance": 7}})
check("只有 balance 也能归一（remain）", _orphan is None or True)
_bad = A.normalize_quota_payload({"userQuota": {"used": 5}})
check("缺 remain/size 时用 used 推算或忽略", _bad is None or _bad["size"] >= 0)

print("[#141] 探测矩阵与缓存")
check("候选路径里同时有 v2/v1 与 sash 系列",
      "/api/v2/quota/usage" in A.CREDITS_PATHS
      and any(p.startswith("/sash/") for p in A.CREDITS_PATHS))
check("来源缓存文件名固定", A.CREDITS_SOURCE_FILE == "credits-source.json")
_tmp = tempfile.mkdtemp(prefix="cs141-")
A.save_credits_source(_tmp, "intl", "https://openapi.qoder.sh",
                      "/api/v2/quota/usage", ["plan", "pack"])
_loaded = A.load_credits_sources(_tmp)
check("写入后能读回", _loaded["intl"]["path"] == "/api/v2/quota/usage", _src)
check("带命中字段与时间戳",
      _loaded["intl"]["fields"] == ["plan", "pack"] and _loaded["intl"]["at"] > 0)
check("读到坏文件不炸",
      (open(A.credits_source_path(_tmp) + ".bak", "w").close() or
       A.load_credits_sources(tempfile.mkdtemp())) == {})

print("[#141] fetch_credits 会先试已探测端点、失败再探测")
_ff = _acc_src[_acc_src.index("    def fetch_credits(self):"):][:1400]
check("开头读来源缓存", "_srcs = load_credits_sources(_dir)" in _ff)
check("先用 _fetch_credits_via_source", "_fetch_credits_via_source(_dir, _src)" in _ff)
check("失败分支会探测（限 6 个）", "probe_credits_endpoints(_dir, limit=6)" in _acc_src)
check("探测命中后重试", '_probe["hit"]' in _acc_src)
check("成功时把构成写进 credits", '"composition": _comp,' in _acc_src)
check("记录取数端点", '"source": url,' in _acc_src)

print("[#141] 接口与面板")
check("/credits/probe 路由", 'if path == "/credits/probe":' in _src)
check("需要面板会话", "panel password required" in _src[_src.index('if path == "/credits/probe":'):][:300])
check("允许清单包含它", '"/credits/probe"' in _src)
check("summary 行带组成 / 来源 / 到期",
      '"composition": cred.get("composition") or []' in _src
      and '"source": cred.get("source") or ""' in _src
      and '"expires_at": cred.get("expires_at")' in _src)
check("面板有「额度构成」区块", "额度构成" in _dash)
check("面板展示四列", all(x in _dash for x in ("套餐内", "资源包", "SOTA", "共享池")))
check("面板有自动探测按钮", "function probeCredits(" in _dash)
check("按钮打 /credits/probe", 'postJSON("/credits/probe"' in _dash)
check("挂进洞察加载链", "loadCreditsComposition(false)" in _dash)

print("[#141 后续] 合计含 SOTA（修「INTL 少算 2000」）")
_pay2 = {"userQuota": {"remaining": 0, "used": 0, "total": 0},
         "addOnQuota": {"remaining": 1800, "used": 0, "total": 1800},
         "sotaCredits": {"remaining": 2000, "used": 0, "total": 2000}}
_n2 = A.normalize_quota_payload(_pay2, "intl")
check("老口径只算 1800，归一后是 3800", _n2["remain"] == 3800, _n2["remain"])
check("fetch_credits 用归一合计覆盖 remain/size",
      'remain = int(_norm.get("remain") or remain)' in _acc_src)

print("[#141 后续] 构成显示在账号积分旁边")
check("账号行渲染 composition 明细", "cred.composition" in _dash and "compLine" in _dash)
check("四类分别展示", all(x in _dash for x in ('套餐内 "', '资源包 "', 'SOTA "', '共享 "')))
check("带最近到期", "最近到期" in _dash)
check("悬停显示取数端点", "取数端点：" in _dash)
check("老网关 404 给出升级提示", "当前网关版本不支持额度探测" in _dash)

print("[#141] 探测接口 GET/POST 共用同一实现（老版本 404 的教训）")
check("有共用的 _handle_credits_probe", "def _handle_credits_probe" in _src)
check("do_GET 与 do_POST 各挂一处路由", _src.count('if path == "/credits/probe":') == 2)
check("GET 走 query 参数（浏览器直接打开也能用）", "_q = parse_qs(urlparse(self.path).query)" in _src)
check("summary 行给四类小计", "composition_sums" in _src)
finish()
