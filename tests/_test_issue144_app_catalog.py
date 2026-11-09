"""Issue144: app-only conversational models are discoverable, chat wins duplicates."""
import os,sys,json,copy,tempfile,types,io
from unittest import mock
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from _suite_head import *
P,A=bootstrap()
import qoder_catalog as C
import qoder_sign as S
import _refresh_catalog as R
declare_suite(__file__,['qoder_proxy.py','qoder_catalog.py','_refresh_catalog.py','qoder_catalog_cn.json','qoder_catalog_intl.json'])
duck={'key':'lmodel','display_name':'QoDuck','enable':True,'price_factor':0.0,'original_price_factor':0.5,'is_free':True,'is_new':True,'is_vl':True,'is_reasoning':True,'max_input_tokens':180000,'context_config':{'200K':{'token_count':200000,'is_default':True},'1M':{'token_count':1000000}},'thinking_config':{'disabled':{},'enabled':{'efforts':{'high':{'is_default':True},'low':{},'xhigh':{}}}}}
chat={'key':'shared','display_name':'Chat authority','enable':False,'price_factor':4,'strategies':[{'enabled':False}]}
payload={'chat':[chat],'app':[{'key':'shared','display_name':'Different app name','enable':True,'price_factor':0},duck,duck], 'inline':[{'key':'completion-test'}], 'quest':[{'key':'quest-only'}]}
original=copy.deepcopy(payload)
rows=C.dialogue_models(payload)
check('chat + app-only deduplicated in stable order',[m['key'] for m in rows]==['shared','lmodel'])
check('chat price/permissions never overwritten by app',rows[0]==chat)
check('app-only metadata stays exact',rows[1]==duck)
check('source not mutated and top-level copies isolated',payload==original and rows[1] is not duck)
for bad in [None,[],{'chat':None,'app':{}},{'chat':[None,{}, {'key':[]},{'key':'  '}],'app':[0]}]:
 check('invalid catalog shape degrades to empty',C.dialogue_models(bad)==[],bad)
check('app-only works without chat',C.dialogue_models({'app':[duck]})==[duck])
check('old chat-only schema unchanged',C.dialogue_models({'chat':[chat]})==[chat])
for realm in ['cn','intl']:
 m=next(x for x in C.models_for_realm(realm) if x['key']=='lmodel')
 check(realm+' snapshot advertises official QoDuck',m['display_name']=='QoDuck' and m['is_free'] is True and m['price_factor']==0)
 check(realm+' aliases resolve to real key',P.resolve_model_key('QoDuck',realm)=='lmodel' and P.resolve_model_key('lmodel',realm)=='lmodel')
 emb=json.loads(C._CN_JSON if realm=='cn' else C._INTL_JSON)
 # fork：内嵌快照保留**官方** max_input_tokens（180000），运行时目录由
 # _align_context_floor 按「context_config 声明了 1M 档」对齐到 1000000
 # （2026.10.17 起，实测输入 883298 成功）。上游断言 embedded==runtime 在
 # fork 不成立——对齐是刻意的，不是抄错。
 _emb_lm=next(x for x in emb if x['key']=='lmodel')
 check(realm+' embedded keeps official launch metadata',_emb_lm.get('max_input_tokens')==180000 and _emb_lm.get('display_name')=='QoDuck',_emb_lm.get('max_input_tokens'))
 entry=P.model_entry('lmodel',m,realm)
 check(realm+' public entry preserves zero price and original price',entry['id']=='QoDuck' and entry['price_factor']==0 and entry['original_price_factor']==0.5 and entry['is_free'])
 # fork：max_input_tokens 走 _align_context_floor（声明 1M 档 -> 1000000）。
 check(realm+' capability/context/reasoning not fabricated',entry['supports_vision'] and entry['supports_reasoning'] and entry['max_input_tokens']==1000000 and entry['reasoning_default_effort']=='high',entry.get('max_input_tokens'))
check('QoDuck is not falsely region-exclusive',P.exclusive_realm('QoDuck')=='' and C.key_realm_span('lmodel')==('cn','intl'))
with tempfile.TemporaryDirectory() as d:
 path=os.path.join(d,'catalog-v7');open(path,'wb').write(b'synthetic-encrypted')
 plain=json.dumps(payload).encode()
 # fork 性能补丁：read_local_models 先读落盘缓存（ACCOUNTS_DIR/local-catalog-<realm>.json，
 # 7 天 TTL）——测试必须隔离 ACCOUNTS_DIR，否则会读到本机真实缓存而不是桩数据。
 with mock.patch.object(S,'qmc_decrypt',return_value=plain),mock.patch.object(P,'local_catalog_files',return_value=[(path,'fixture')]),mock.patch.object(P,'ACCOUNTS_DIR',d):
  local=P.read_local_models('cn')
 check('local decoder includes app-only model',[m for m,_ in local]==['shared','lmodel'])
 with mock.patch.object(R,'qmc_decrypt',return_value=plain):
  exported=R.read_chat_models(path)
 check('snapshot refresh shares exact extraction rule',exported==rows)
 fake=types.SimpleNamespace(headers=lambda *a,**k:{})
  # fork：出站走 UPSTREAM_OPENER，patch P.urllib.request.urlopen 拦不到（第 5 次同型）
 with mock.patch.object(P,'POOL',types.SimpleNamespace(pick=lambda **k:object())),mock.patch.object(P.SESSIONS,'get',return_value=fake),mock.patch.object(P,'gateway_candidates',return_value=['https://example.invalid']),mock.patch.object(P,'validate_public_http_url',side_effect=lambda x:x),mock.patch.object(A.UpstreamOpener,'_stub',return_value=io.BytesIO(plain)):
  live=P.read_dynamic_models('cn')
 check('online discovery includes app-only QoDuck',[m for m,_ in live]==['shared','lmodel'])
 check('live metadata retains false and zero values',live[0][1]['enable'] is False and live[1][1]['price_factor']==0)
 with mock.patch.object(P,'ACCOUNTS_DIR',d):
  P._save_models_cache('cn',live)
  check('disk cache round trip keeps app model',any(mid=='lmodel' and meta['display_name']=='QoDuck' for mid,meta in P._load_models_cache('cn')))
 with mock.patch.object(P,'read_dynamic_models',return_value=live),mock.patch.object(P,'_save_models_cache'),mock.patch.object(P,'_models_cache',{}),mock.patch.object(P,'_offline_models_cache',{}):
  merged=P.fetch_models('cn')
 check('fetch/merge does not re-drop app-only model',any(mid=='lmodel' for mid,_ in merged))
 check('fresh authoritative live list does not resurrect unrelated static models',len(merged)==2)
finish()
