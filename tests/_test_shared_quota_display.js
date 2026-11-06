/* 直接运行发布页面中的共享额度渲染函数，检查用户可见文本。 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const {extract, fnBody} = require('./_tools/dash_extract.js');
const htmlPath = process.env.QD_SHARED_TEST_DASH || path.join(__dirname, '..', 'dashboard.html');
const {code} = extract(htmlPath);
const raw = fs.readFileSync(htmlPath);
console.log('SUITE: ' + path.basename(__filename) + ' md5=' + crypto.createHash('md5').update(fs.readFileSync(__filename)).digest('hex'));
console.log('FILE: dashboard.html md5=' + crypto.createHash('md5').update(raw).digest('hex') + ' bytes=' + raw.length + ' as-of=' + new Date().toISOString());
let pass = 0, fail = 0;
function check(label, cond, detail){
  if(cond){ pass++; console.log('  [PASS] ' + label); }
  else { fail++; console.log('  [FAIL] ' + label + ' ' + JSON.stringify(detail)); }
}
const body = fnBody(code, 'sharedCreditsTag');
check('共享额度渲染器存在', !!body);
if(body){
  const render = new Function('fmt', body + '\nreturn sharedCreditsTag;')(x => x == null ? '?' : String(x));
  const visible = value => render(value).replace(/<[^>]*>/g, '');
  const text = visible({used:254, remain:5746, size:6000, available:true});
  check('已用、上限和剩余都在可见文本中', ['已用 254', '上限 6000', '剩余 5746'].every(s => text.includes(s)), text);
  check('额度耗尽仍显示真实已用和零余额', visible({used:6000, remain:0, size:6000}).includes('已用 6000 / 上限 6000 · 剩余 0'));
  check('不可用共享池明确标注', visible({used:50, remain:50, size:100, available:false}).includes('不可用'));
  const unlimited = visible({used:254, remain:1000000, size:-1, unlimited:true});
  check('不限量不能显示负上限或占位余额', unlimited.includes('不限量') && !unlimited.includes('-1') && !unlimited.includes('1000000'), unlimited);
  check('零额度不是未知状态', visible({used:0, remain:0, size:0}).includes('上限 0 · 剩余 0'));
  check('没有共享字段时不凭空展示额度', render(null) === '' && render({used:1}) === '');
  check('账号行使用同一渲染器', fnBody(code, 'accountRow').includes('sharedCreditsTag(cred && cred.shared)'));
  const start = code.indexOf('/* BEGIN-PURE-I18N-CORE');
  const end = code.indexOf('/* END-PURE-I18N-CORE */');
  if(start < 0 || end <= start) throw new Error('缺少真实翻译引擎锚点');
  const translator = new Function('"use strict";' + code.slice(start, end) + '\nreturn {t, load};')();
  translator.load(JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'i18n/en.json'), 'utf8')));
  for(const shared of [
    {used:254, remain:5746, size:6000},
    {used:254, remain:1000000, size:-1, unlimited:true},
    {used:50, remain:50, size:100, available:false},
  ]){
    const english = translator.t(visible(shared));
    check('共享用量通过真实语言包完整翻译', english.includes('Shared: used') && !/[\u4e00-\u9fff]/.test(english), english);
  }

}
console.log('\nSUMMARY: TOTAL ' + (pass+fail) + ' checks, ' + pass + ' passed, ' + fail + ' failed, 0 skipped');
console.log('RESULT: ' + (fail ? 'RED' : 'GREEN'));
process.exit(fail ? 1 : 0);
