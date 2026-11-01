import assert from 'node:assert/strict';
const client='/Applications/ChatGPT.app/Contents/Resources/cua_node/lib/node_modules/@oai/cua/dist/lib/js/oai_js_browser/dist/skill/scripts/browser-client.js';
const desktop='/Applications/ChatGPT.app/Contents/Resources/cua_node/lib/node_modules/@oai/browser-desktop/scripts/browser-client.mjs';
const results=[];
for(const path of [client,desktop]){
 const calls=[];let failure;
 globalThis.nodeRepl={env:{},emitImage:async()=>{},rpc:async(service,{method,params})=>{
  calls.push({service,method,params});
  if(method==='setup')return {apiManifest:{root:'Agent',interfaces:{Agent:{},Browsers:{},Browser:{},Tabs:{},Tab:{close:{}}}},disabledMemberIds:['Tab.close'],credentialRecoveryErrorVersion:1};
  if(failure)return{ok:false,error:failure};
  return{ok:true,value:params.type==='get_browser'?{id:'7',type:'iab',capabilities:{}}:params.type==='get_tab'?{id:'42'}:{}};
 }};
 const {setupBrowserRuntime}=await import(path);const agent=await setupBrowserRuntime();const browser=await agent.browsers.get('iab');const tab=await browser.tabs.get('42');
 assert.equal(tab.close,undefined);assert.equal('close' in tab,false);await tab.goto('https://example.invalid/');
 assert.equal(calls[0].method,'setup');assert.equal(calls[0].params.environment,'codex-app');assert.ok(calls.slice(1).every(x=>x.service==='browser'&&x.method==='executeWithRecovery'));
 assert.deepEqual(calls.at(-1).params,{type:'navigate_tab_url',browser_id:'7',tab_id:'42',url:'https://example.invalid/',client_timeout_ms:undefined});
 failure={schema_version:1,command:'get_tab',phase:'before_command',reason:'credential_delivery_in_progress',next_action:'retry_after_credential_delivery'};
 await assert.rejects(()=>browser.tabs.get('42'),e=>e.name==='BrowserCredentialRecoveryError'&&e.details.reason==='credential_delivery_in_progress');
 results.push({path,checks:['setup environment default','trusted browser RPC namespace','executeWithRecovery v1 negotiation','browser/tab bound command IDs','disabled member inaccessible through get/has','typed credential recovery'],capturedCommands:calls.map(x=>({method:x.method,type:x.params?.type,browser_id:x.params?.browser_id,tab_id:x.params?.tab_id}))});
}
console.log(JSON.stringify(results,null,2));
