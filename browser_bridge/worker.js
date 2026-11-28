const BASE="http://127.0.0.1:18746";
let busy=false;
chrome.alarms.create("btc-lab",{periodInMinutes:1});
chrome.alarms.onAlarm.addListener(a=>{if(a.name==="btc-lab")poll();});
chrome.runtime.onMessage.addListener((m,sender)=>{if(sender.id===chrome.runtime.id&&sender.url===chrome.runtime.getURL("popup.html")&&m.action==="poll")poll();});
async function api(key,path,body){
  const r=await fetch(BASE+path,{method:body?"POST":"GET",headers:{"Authorization":"Bearer "+key,...(body?{"Content-Type":"application/json"}:{})},body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(5000)});
  if(!r.ok)throw Error("Local relay HTTP "+r.status);
  return r.json();
}
// Only composer/control state is inspected; never read or export assistant output.
function inspect(expected){
  if(location.origin+location.pathname!==expected)return "wrong_chat";
  const visible=e=>!!e&&e.getClientRects().length>0;
  if(visible(document.querySelector('[data-testid="stop-button"],button[aria-label="Stop generating"]')))return "busy";
  const p=document.querySelector('#prompt-textarea');
  if(!visible(p)||!(p.isContentEditable||p.tagName==="TEXTAREA")||p.getAttribute("aria-disabled")==="true")return "unavailable";
  if((p.value??p.innerText??"").trim())return "draft_exists";
  return "ready";
}
async function insertAndSend(expected,text){
  if(location.origin+location.pathname!==expected)return "wrong_chat";
  const p=document.querySelector('#prompt-textarea');
  if(!p||!(p.isContentEditable||p.tagName==="TEXTAREA")||p.getAttribute("aria-disabled")==="true"||(p.value??p.innerText??"").trim()||document.querySelector('[data-testid="stop-button"]'))return "not_ready";
  p.focus();
  if(!document.execCommand("insertText",false,text))return "insert_failed";
  await new Promise(r=>setTimeout(r,450));
  if(location.origin+location.pathname!==expected)return "wrong_chat";
  const send=document.querySelector('button[data-testid="send-button"]');
  if(!send||!send.getClientRects().length||send.disabled||send.getAttribute("aria-disabled")==="true"||document.querySelector('[data-testid="stop-button"]'))return "send_unavailable";
  // Confirm the exact prepared user draft, not any assistant text.
  if((p.value??p.innerText??"").trim()!==text.trim())return "draft_changed";
  send.click();
  // Observe only composer/control state, never the assistant's response.
  // This is a local observation, not proof of server acceptance.
  for(let i=0;i<20;i++){
    await new Promise(r=>setTimeout(r,500));
    if(location.origin+location.pathname!==expected)return "wrong_chat";
    if(document.querySelector('[data-testid="stop-button"],button[aria-label="Stop generating"]'))return "clicked";
    const current=document.querySelector('#prompt-textarea');
    if(current&&!(current.value??current.innerText??"").trim()&&
       (current.isContentEditable||current.tagName==="TEXTAREA")&&current.getAttribute("aria-disabled")!=="true")return "clicked";
  }
  return "send_not_confirmed";
}
async function inject(tabId,func,args){const r=await chrome.scripting.executeScript({target:{tabId},func,args});return r[0]?.result;}
async function poll(){
 if(busy)return;busy=true;
 let s,claimed=null;
 try{
  s=await chrome.storage.local.get(["armed","url","tabId","key"]);
  if(!s.armed)return;
  const event=await api(s.key,"/next");
  if(!event.id)return;
  const t=await chrome.tabs.get(s.tabId).catch(()=>null);
  if(!t?.url||new URL(t.url).origin+new URL(t.url).pathname!==s.url){
    const grant=await api(s.key,"/claim",{id:event.id});
    if(grant.ok)await api(s.key,"/ack",{id:event.id,status:"blocked"});
    await chrome.storage.local.set({armed:false,status:"Чат закрыт или изменён. Привяжи заново."});return;
  }
  if(!/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(event.id)||typeof event.message!=="string"||event.message.length>1200)throw Error("Invalid event");
  const state=await inject(s.tabId,inspect,[s.url]);
  if(state==="busy"||state==="draft_exists"){await chrome.storage.local.set({status:"Ожидаю: "+state});return;}
  if(state!=="ready"){
    const grant=await api(s.key,"/claim",{id:event.id});
    if(grant.ok)await api(s.key,"/ack",{id:event.id,status:"blocked"});
    await chrome.storage.local.set({armed:false,status:"Остановлено: "+state});return;
  }
  const counts=await chrome.storage.local.get(["sent"]);
  if((counts.sent||0)>=20){
    const grant=await api(s.key,"/claim",{id:event.id});
    if(grant.ok)await api(s.key,"/ack",{id:event.id,status:"blocked"});
    await chrome.storage.local.set({armed:false,status:"Лимит пилота: 20 сообщений. Требуется ручная проверка."});return;
  }
  if(!(await chrome.storage.local.get("armed")).armed)return;
  const grant=await api(s.key,"/claim",{id:event.id});
  if(!grant.ok)return;
  claimed=event.id;
  const result=await inject(s.tabId,insertAndSend,[s.url,event.message]);
  await api(s.key,"/ack",{id:claimed,status:result==="clicked"?"clicked":"blocked"});
  await chrome.storage.local.set({status:result==="clicked"?"Нажата отправка "+claimed:"Отправка не подтверждена: "+result,armed:result==="clicked",sent:(counts.sent||0)+(result==="clicked"?1:0)});
 }catch(e){
  if(claimed&&s?.key){try{await api(s.key,"/ack",{id:claimed,status:"blocked"});}catch{}await chrome.storage.local.set({armed:false,status:"Неопределённая отправка. Повтор запрещён."});}
  else await chrome.storage.local.set({status:String(e.message).slice(0,150)});
 }finally{busy=false;}
}
