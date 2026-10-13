const test = require('node:test');
const assert = require('node:assert/strict');
const load = require('./load-ts.cjs');
test('Portal upstream failures retain provider message instead of UF/auth text', async () => {
  const {apiClient,ApiError}=load('@/lib/api/client');
  const prior=global.fetch;
  global.fetch=async()=>new Response(JSON.stringify({detail:{code:'portal_access_denied',message:'Portal rechazó el acceso a la publicación.'}}),{status:503});
  try {await assert.rejects(apiClient.post('/api/v1/listings/lookup-url',{url:'https://www.portalinmobiliario.com/MLC-123'},{token:null}),e=>e instanceof ApiError&&e.status===503&&e.message==='Portal rechazó el acceso a la publicación.');}
  finally {global.fetch=prior;}
});
test('Radar displays the Tasar engine result and its matching discount', () => {
  const {opportunity} = load('@/features/radar/model');
  const result = opportunity({listing_id:1130, price_uf:1520, estimated_price_uf:2376.63,
    estimated_value_uf:2376.63, discount_pct:36.04, consensus_used:true, valuation_strategy:"consensus_v1", warnings:[], confidence_risk_flags:[]});
  assert.equal(result.estimate,2376.63);
  assert.equal(result.valuationMethod,"Consenso Valoria");
  assert.match(result.evidence,/motor de Tasar/);
  assert.ok(Math.abs((1-result.price/result.estimate)*100-result.discount)<0.01);
});
test('withdrawn status dominates even an obsolete fresh label', () => {
  const {freshnessText} = load('@/features/listing-url/view-model');
  assert.match(freshnessText({listing_status:'removed',freshness_status:'already_fresh'}),/histórica/);
  assert.match(freshnessText({}),/no está confirmada/);
});
test('model warnings explain fallback and preserve unknown codes', () => {
  const {mapWarningCodes} = load('@/features/valuation/warning-taxonomy');
  const codes=['property_type_not_allowed','delta_vs_baseline_too_high','published_price_not_provided','future_critical_warning'];
  const result=mapWarningCodes(codes);
  assert.deepEqual(result.map(r=>r.code),codes);
  assert.ok(result.slice(0,3).every(r=>r.known));
  assert.equal(result[2].severity,'info');
  assert.equal(result[3].severity,'warning');
});
test('search covers commune and accented title with normalized whitespace', () => {
  const {matchesPropertySearch} = load('@/lib/search');
  const item={title:'Departamento México',comuna:'la_florida',description:''};
  assert.ok(matchesPropertySearch(item,'La   Florida'));
  assert.ok(matchesPropertySearch(item,' MEXICO '));
  assert.ok(!matchesPropertySearch(item,'xico'));
  assert.ok(!matchesPropertySearch(item,'Florida Blanca'));
});
test('thumbnails use only valid signed derived-image references', () => {
  const {thumbnailSrc}=load('@/lib/thumbnail');
  const hash='a'.repeat(64),ref={hash,width:320,height:240,bytes:9000,url:`/api/v1/thumbnails/${hash}.webp?expires=9999999999&sig=${'b'.repeat(64)}`};
  assert.equal(thumbnailSrc(ref),'/backend'+ref.url);
  assert.equal(thumbnailSrc({...ref,url:'https://example.com/full-image.jpg'}),null);
  assert.equal(thumbnailSrc({...ref,width:0}),null);
  assert.equal(thumbnailSrc(null),null);
});
test('Radar analyzer selection is consumed once and stays editable', () => {
  const store=new Map();global.window={sessionStorage:{setItem:(k,v)=>store.set(k,v),getItem:k=>store.get(k)??null,removeItem:k=>store.delete(k)}};
  const {saveAnalyzerPrefill,consumeAnalyzerPrefill}=load('@/features/listing-url/prefill');
  saveAnalyzerPrefill('https://www.yapo.cl/test/1130');
  assert.equal(consumeAnalyzerPrefill(),'https://www.yapo.cl/test/1130');
  assert.equal(consumeAnalyzerPrefill(),null);
  assert.throws(()=>saveAnalyzerPrefill('javascript:alert(1)'));
  delete global.window;
});

test('session changes invalidate same-tab and other-tab account state', () => {
  const events=new EventTarget(),store=new Map();let resets=0;
  global.window={localStorage:{getItem:k=>store.get(k)??null,setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)},addEventListener:events.addEventListener.bind(events),removeEventListener:events.removeEventListener.bind(events),dispatchEvent:events.dispatchEvent.bind(events)};
  const auth=load('@/lib/auth/token');const dispose=auth.observeSessionChange(()=>resets++);
  auth.setAccessToken('account-a');auth.setAccessToken('account-a');assert.equal(resets,1);
  auth.clearAccessToken();assert.equal(resets,2);assert.equal(auth.getAccessToken(),null);
  const unrelated=new Event('storage');unrelated.key='unrelated';events.dispatchEvent(unrelated);assert.equal(resets,2);
  const changed=new Event('storage');changed.key=auth.TOKEN_KEY;events.dispatchEvent(changed);assert.equal(resets,3);
  dispose();auth.setAccessToken('account-b');assert.equal(resets,3);delete global.window;
});
