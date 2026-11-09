"""QD_CN_VPC_ENDPOINT 企业 VPC 专属域套件。

判据：
  1. 解析只接受实例名或 vpc.qoder.com.cn 下的三种官方域名，拒绝路径 /
     端口 / 凭据 / query / fragment，防止只改掉流程里的一部分端点；
  2. 配置后 CN 的 openapi / gateway / website 全部切换到专属域，且
     openapi / gateway 候选**不允许**回退到公网；
  3. 专属域解析到内网地址时，两处 SSRF 校验只放行这三个推导主机；
     未配置的 vpc.qoder.com.cn 域名仍按公网规则拒绝；
  4. 未设置环境变量时，现有 CN 行为逐字节不变。

    python tests/_test_vpc_endpoint.py
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _suite_head import ROOT, bootstrap, check, declare_suite, finish  # noqa: E402

os.environ.pop("QD_CN_VPC_ENDPOINT", None)
os.environ.pop("QD_CN_OPENAPI", None)
P, A = bootstrap()
declare_suite(__file__, ["qoder_accounts.py", "qoder_proxy.py"])

print("\n[vpc] 1) 解析：实例名与三种官方域名")
CASES = {
    "acme": ("acme", "https://acme.vpc.qoder.com.cn",
             "https://acme-openapi.vpc.qoder.com.cn",
             "https://acme-gateway.vpc.qoder.com.cn"),
    "ACME.VPC.QODER.COM.CN": ("acme", "https://acme.vpc.qoder.com.cn",
                              "https://acme-openapi.vpc.qoder.com.cn",
                              "https://acme-gateway.vpc.qoder.com.cn"),
    "https://acme-openapi.vpc.qoder.com.cn/": (
        "acme", "https://acme.vpc.qoder.com.cn",
        "https://acme-openapi.vpc.qoder.com.cn",
        "https://acme-gateway.vpc.qoder.com.cn"),
    "acme-gateway.vpc.qoder.com.cn": (
        "acme", "https://acme.vpc.qoder.com.cn",
        "https://acme-openapi.vpc.qoder.com.cn",
        "https://acme-gateway.vpc.qoder.com.cn"),
}
for value, expected in CASES.items():
    got = A.parse_vpc_endpoint(value)
    actual = ((got or {}).get("instance"), (got or {}).get("website"),
              (got or {}).get("openapi"), (got or {}).get("gateway"))
    check("解析 %r" % value, actual == expected, actual)

check("空值 = 未配置（返回 None）", A.parse_vpc_endpoint("") is None)

print("\n[vpc] 2) 解析：拒绝部分重定向输入")
BAD = (
    "  acme", "acme  ", "acme\n", "acme:8443",
    "acme/path", "acme?x=1", "acme#frag",
    "other.example.com", "acme.vpc.qoder.com.cn.evil.test",
    "ftp://acme", "u:p@acme.vpc.qoder.com.cn",
    "acme..vpc.qoder.com.cn", "-acme", "acme-",
)
for value in BAD:
    try:
        A.parse_vpc_endpoint(value)
        ok = False
    except ValueError:
        ok = True
    check("拒绝 %r" % value, ok)

print("\n[vpc] 3) 未配置：现有 CN 行为不变")
check("CN openapi 仍是公网",
      A.get_realm_config("cn")["openapi"] == "https://openapi.qoder.com.cn")
check("CN gateway 仍是单一官方主机",
      A.gateway_candidates("cn") == ["https://gateway.qoder.com.cn"])
check("CN openapi 候选不含 VPC 域",
      not any("vpc.qoder.com.cn" in c for c in A.openapi_candidates("cn")))
check("未配置时 is_configured_vpc_host 为 False",
      not A.is_configured_vpc_host("acme-openapi.vpc.qoder.com.cn"))


def run_py(code, env_extra):
    env = dict(os.environ)
    env.pop("QD_CN_OPENAPI", None)
    env["PYTHONPATH"] = os.pathsep.join(
        [ROOT] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    env.update(env_extra)
    out = subprocess.check_output([sys.executable, "-c", code],
                                  cwd=ROOT, env=env, text=True,
                                  stderr=subprocess.STDOUT, timeout=60)
    return out.strip().splitlines()[-1]


print("\n[vpc] 4) 子进程：QD_CN_VPC_ENDPOINT=acme 的模块状态")
CODE = r'''
import json
import qoder_accounts as A
cn = A.get_realm_config("cn")
print(json.dumps({
    "error": A.vpc_config_error(),
    "instance": A.vpc_instance(),
    "openapi": cn["openapi"],
    "gateway": cn["gateway"],
    "website": cn["website"],
    "domain": cn["domain"],
    "openapi_candidates": A.openapi_candidates("cn"),
    "gateway_candidates": A.gateway_candidates("cn"),
    "hosts": sorted(A.vpc_endpoint_hosts()),
}, ensure_ascii=False))
'''
data = json.loads(run_py(CODE, {"QD_CN_VPC_ENDPOINT": "acme"}))
check("配置读取无错误", data["error"] == "", data["error"])
check("实例名 = acme", data["instance"] == "acme", data["instance"])
check("openapi = 专属域",
      data["openapi"] == "https://acme-openapi.vpc.qoder.com.cn", data["openapi"])
check("gateway = 专属域",
      data["gateway"] == "https://acme-gateway.vpc.qoder.com.cn", data["gateway"])
check("website = 专属域",
      data["website"] == "https://acme.vpc.qoder.com.cn", data["website"])
check("domain = 专属域",
      data["domain"] == "acme.vpc.qoder.com.cn", data["domain"])
check("openapi 候选只有专属域（不回退公网）",
      data["openapi_candidates"] == ["https://acme-openapi.vpc.qoder.com.cn"],
      data["openapi_candidates"])
check("gateway 候选只有专属域（不回退 api1/2/3）",
      data["gateway_candidates"] == ["https://acme-gateway.vpc.qoder.com.cn"],
      data["gateway_candidates"])
check("放行主机集合 = 三个专属域", data["hosts"] == [
    "acme-gateway.vpc.qoder.com.cn",
    "acme-openapi.vpc.qoder.com.cn",
    "acme.vpc.qoder.com.cn",
], data["hosts"])

print("\n[vpc] 5) 子进程：非法值会留下启动错误")
err = run_py("import qoder_accounts as A; print(A.vpc_config_error())",
             {"QD_CN_VPC_ENDPOINT": "bad host"})
check("非法值产生非空错误", bool(err) and "invalid VPC endpoint" in err, err)

print("\n[vpc] 6) 子进程：内网解析时只放行配置的专属域")
CODE_SSRF = r'''
import json
import socket

_orig = socket.getaddrinfo


def fake(host, port, *args, **kwargs):
    if str(host).lower().endswith(".vpc.qoder.com.cn"):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                 ("10.20.30.40", port or 443))]
    return _orig(host, port, *args, **kwargs)


socket.getaddrinfo = fake
import qoder_accounts as A
import qoder_proxy as P

res = {}
for name, fn in (("accounts", A.validate_public_http_url),
                 ("proxy", P.validate_public_http_url)):
    def probe(url):
        try:
            fn(url)
            return "ok"
        except Exception as exc:
            return "blocked:%s" % exc
    res[name + "_vpc"] = probe(
        "https://acme-openapi.vpc.qoder.com.cn/api/v1/userinfo")
    res[name + "_other"] = probe("https://other.vpc.qoder.com.cn/api/v1/userinfo")
print(json.dumps(res, ensure_ascii=False))
'''
ssrf = json.loads(run_py(CODE_SSRF, {"QD_CN_VPC_ENDPOINT": "acme"}))
check("qoder_accounts 放行配置的专属域（即使解析到内网）",
      ssrf.get("accounts_vpc") == "ok", ssrf.get("accounts_vpc"))
check("qoder_proxy 放行配置的专属域（即使解析到内网）",
      ssrf.get("proxy_vpc") == "ok", ssrf.get("proxy_vpc"))
check("未配置的 vpc.qoder.com.cn 仍按内网目标拒绝",
      str(ssrf.get("accounts_other", "")).startswith("blocked:"),
      ssrf.get("accounts_other"))
check("qoder_proxy 同样拒绝未配置的同后缀域名",
      str(ssrf.get("proxy_other", "")).startswith("blocked:"),
      ssrf.get("proxy_other"))

finish()
