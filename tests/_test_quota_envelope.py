# -*- coding: utf-8 -*-
"""#108 额度类 403（112 额度耗尽 / 110 每日次数上限）快速失败套件。

    python tests/_test_quota_envelope.py

钉住五件事：
  1) 112 -> 账号级冷却 1800s，**单号池也不被** single_account 压成 3s；
  2) 110 -> 冷却到下一个本地 0 点（封顶 6h，不短于 60s）；
  3) 112/110 不禁用账号、不喂降权（配额问题不是凭证失效/未知故障）；
  4) 10605 / isQueued 仍然零冷却（#71 的既有行为不能被这次改动破坏）；
  5) 两条分类点（envelope + open_upstream）都接了额度判断。
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _suite_head import *          # noqa: F401,F403

P, A = bootstrap()
declare_suite(__file__, ["qoder_proxy.py", "qoder_accounts.py"])

MODEL = "gfmodel"

# 上游原文（2026-10-27 现场日志；112 的 message 是二次转义的 JSON 字符串）
D112 = ('{"code":"112","message":"{\\"pricingUrl\\":\\"https://qoder.com.cn/'
        'pricing?client=qoder\\"}"}')
D110 = '{"code":"110","message":"Billing daily count exceeded"}'
D10605 = ('{"code":"403","message":"{\\"code\\":\\"10605\\",\\"isQueued\\":true,'
          '\\"retryAfterSeconds\\":30}"}')


def build(n=1, realm="cn"):
    """真实 Account + AccountPool：下面的冷却数字由**真的** note_error 算出来。"""
    accs = []
    for i in range(n):
        a = A.Account({"uid": "q108-%d" % i, "realm": realm,
                       "accessToken": "dt-q108-%d" % i})
        a.expires_at = time.time() + 86400
        accs.append(a)
    pool = A.AccountPool(tempfile.mkdtemp(), log=lambda *a, **k: None)
    pool.accounts = accs
    return pool, accs


def wait_of(acc):
    """本账号还要等多少秒才能再服务 MODEL（0 = 现在就能用）。"""
    return acc.throttle_wait(model=MODEL)


# ---------------------------------------------------------------- 判据
check("#108 112 认得（现场原文，含 pricingUrl）",
      P._quota_cooldown(D112) == ("exhausted", 1800), P._quota_cooldown(D112))
check("#108 112 认得（日志里的转义形态 \\\"code\\\":\\\"112\\\"）",
      P._quota_cooldown('{\\"code\\":\\"112\\"}')[0] == "exhausted",
      P._quota_cooldown('{\\"code\\":\\"112\\"}'))
check("#108 110 认得（原文 Billing daily count exceeded）",
      P._quota_cooldown(D110)[0] == "daily", P._quota_cooldown(D110))
check("#108 110 认得（纯 code 形态）",
      P._quota_cooldown('{"code":"110"}')[0] == "daily")
check("#108 普通 403 不误判成额度",
      P._quota_cooldown('{"code":"forbidden"}') == ("", 0),
      P._quota_cooldown('{"code":"forbidden"}'))
check("#108 10605 排队不误判成额度",
      P._quota_cooldown(D10605)[0] == "", P._quota_cooldown(D10605))

# ---------------------------------------------------------------- 112 单号池
P.POOL, _accs = build(1)
_ONE = _accs[0]
check("#108 单号池口径 = 1（下面「不被 clamp」的断言才有证据）",
      P._realm_ready_total("cn", MODEL) == 1, P._realm_ready_total("cn", MODEL))
P._handle_envelope_account_cooldown(_ONE, P.UpstreamStatus(403, D112), model=MODEL)
_w = wait_of(_ONE)
check("#108 112 -> 模型级冷却 3600s（1 小时）", 3590 <= _w <= 3610, _w)
check("#108 112 单号池不被 single_account 压成 3s", _w > 60, _w)
check("#108 112 不禁用账号（配额不是凭证失效）", _ONE.enabled is True, _ONE.enabled)
check("#108 112 不喂降权（配额不是未知故障）", _ONE.degrade_count == 0, _ONE.degrade_count)
# fork 语义（2026-10-09/10-20 实测定案）：112 是**该模型**对 Free 计划收费，
# 与账号余额无关——账号换模型照样能干活，故只冷却**模型**、不冷却整个账号。
# 上游 #108 把 112 当「账号额度耗尽」冷却账号 30min，在本 fork 会误伤可用号。
check("#108 112 写模型级冷却、且不冷却整个账号（fork 模型付费墙语义）",
      bool(_ONE.model_cooldowns)
      and _ONE.cooldown_until <= time.time() + 1,
      (_ONE.model_cooldowns, _ONE.cooldown_until))

# ---------------------------------------------------------------- 110 单号池
P.POOL, _accs = build(1)
_TWO = _accs[0]
P._handle_envelope_account_cooldown(_TWO, P.UpstreamStatus(403, D110), model=MODEL)
_w2 = wait_of(_TWO)
_now = time.time()
# fork 语义：110 冷却挂到**计费日翻转**（每日 10:00 UTC+8，与配额护栏/402
# 停放同源，issue #20），不是上游的「本地 0 点封顶 6h」——按 6h 封顶会让
# 当日必然再撞的组合提前出冷却、白付一轮探测。
_reset, _when = P._daily_reset_window(_now)
_expect = _reset - _now
check("#108 110 -> 冷却到计费日翻转（fork 口径）", abs(_w2 - _expect) <= 5, (_w2, _expect))
check("#108 110 冷却不短于 60s", _w2 >= 59, _w2)
check("#108 110 不禁用账号", _TWO.enabled is True, _TWO.enabled)

# ---------------------------------------------------------------- 10605 不回归
P.POOL, _accs = build(1)
_Q = _accs[0]
P._handle_envelope_account_cooldown(_Q, P.UpstreamStatus(403, D10605), model=MODEL)
check("#108 10605 排队仍然零冷却（#71 不被破坏）",
      wait_of(_Q) <= 0.001 and not _Q.model_cooldowns,
      (wait_of(_Q), _Q.model_cooldowns))

# ---------------------------------------------------------------- 多号池也照冷
P.POOL, _accs = build(2)
_M = _accs[0]
P._handle_envelope_account_cooldown(_M, P.UpstreamStatus(403, D112), model=MODEL)
check("#108 多号池下 112 同样冷却 3600s", 3590 <= wait_of(_M) <= 3610, wait_of(_M))

# ---------------------------------------------------------------- 客户端文案
_msg, _kind = P.friendly_upstream_error(403, D112)
# fork 语义：112 是模型付费墙（不是账号额度耗尽）——文案必须说清「换个模型
# 即可」，否则用户会去充值，白花冤枉钱。上游文案「账号额度耗尽，请充值」
# 在本 fork 属误诊（实测同账号同刻 auto=112、Qwen3.8-Flash=10605 仍可用）。
check("#108 客户端文案点明模型付费墙（fork 语义）",
      "Free 计划" in _msg and _kind == "upstream_paid_wall",
      (_kind, _msg[:60]))
# fork 不变量：排队文案用 Zcode 白名单值 no_capacity（upstream 的
# upstream_queued 会被 Zcode 判 unknown、整回合判死）。
check("#108 排队文案不被额度文案抢走",
      P.friendly_upstream_error(403, D10605)[1] == "no_capacity",
      P.friendly_upstream_error(403, D10605)[1])

# ---------------------------------------------------------------- 接线
_src = io.open(os.path.join(ROOT, "qoder_proxy.py"), encoding="utf-8").read()
# fork 的额度分类走 _apply_110_cooldown（模型级起步、两模型连撞升级账号级），
# envelope 与 open_upstream 两个分类点各接一次；上游的 _note_quota_cooldown
# 只在 HTTP 路径作兜底（fork 的匹配器更全，漏网的 110 形态由它接）。
check("#108 两条分类点都接了额度判断（envelope + open_upstream）",
      _src.count("= _apply_110_cooldown(account, model)") == 2,
      _src.count("= _apply_110_cooldown(account, model)"))
check("#108 额度判断排在 10605 短路段之后（排队不被额度逻辑吃掉）",
      _src.index("_is_queue71") < _src.index("if _note_quota_cooldown("))

finish()
