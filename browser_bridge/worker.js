const BASE="http://127.0.0.1:18746";
let busy=false;
chrome.alarms.get("btc-lab").then(a=>{if(a?.periodInMinutes!==0.5)chrome.alarms.create("btc-lab",{periodInMinutes:0.5});});
chrome.alarms.onAlarm.addListener(a=>{if(a.name==="btc-lab")poll();});
chrome.runtime.onMessage.addListener((m,sender)=>{if(sender.id===chrome.runtime.id&&sender.url===chrome.runtime.getURL("popup.html")&&m.action==="poll")poll(true);});
async function api(key,path,body){
  const r=await fetch(BASE+path,{method:body?"POST":"GET",headers:{"Authorization":"Bearer "+key,...(body?{"Content-Type":"application/json"}:{})},body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(5000)});
  if(!r.ok)throw Error("Local relay HTTP "+r.status);
  return r.json();
}
// A single injected function for inspection and sending. Never inspect assistant output.
async function composerAction(expected,text=null){
  const correctChat=()=>location.origin+location.pathname===expected;
  if(!correctChat())return "wrong_chat";
  const visible=e=>!!e&&e.isConnected&&e.getClientRects().length>0&&
    getComputedStyle(e).visibility==="visible"&&
    !e.closest('[hidden],[inert],[aria-hidden="true"]');
  const stopSelector='button[data-testid="stop-button"],button[aria-label="Stop generating"],button[aria-label="Остановить генерацию"],button[aria-label="Остановить"],button[aria-label="Stop"]';
  const editable=e=>visible(e)&&(e.isContentEditable||e.tagName==="TEXTAREA")&&
    !e.disabled&&!e.readOnly&&!e.closest('[aria-disabled="true"]');
  const editors='textarea,[contenteditable="true"],[contenteditable="plaintext-only"]';
  const anchors='#prompt-textarea,[data-testid="prompt-textarea"],[data-testid="composer-input"],[data-testid="composer-textarea"],[data-composer-input],[data-composer-markdown][role="textbox"]';
  const sendSelector='button[data-testid="send-button"],button[aria-label="Send message"],button[aria-label="Отправить сообщение"],button[type="submit"][aria-label="Отправить"],button[type="submit"][aria-label="Send"]';
  const findEditor=()=>{
    const nodes=new Set();
    for(const a of document.querySelectorAll(anchors)){
      if(editable(a))nodes.add(a);
      for(const e of a.querySelectorAll(editors))if(editable(e))nodes.add(e);
    }
    // Some versions render a hidden textarea and a separate visible editor.
    // Fallback only inside a form identifiable as the message composer.
    if(!nodes.size){
      for(const f of document.querySelectorAll('form')){
        if(!f.querySelector(anchors+',#composer-submit-button,'+sendSelector))continue;
        for(const e of f.querySelectorAll(editors))if(editable(e))nodes.add(e);
      }
    }
    const candidates=[...nodes].filter(e=>![...nodes].some(other=>other!==e&&other.contains(e)));
    return candidates.length===1?{p:candidates[0],state:"ready"}:
      {p:null,state:candidates.length?"composer_ambiguous":
      "composer_unavailable (anchors="+document.querySelectorAll(anchors).length+
      ", forms="+document.querySelectorAll('form').length+")"};
  };
  const scopeOf=p=>p?.closest("[data-composer-footer-responsive]")||p?.closest("form");
  // Ignore controls outside the current composer, e.g. retained message controls.
  // If the editor is temporarily absent, remain conservative and wait for a visible
  // generation stop control, rather than attempting to send.
  const stopping=(p=findEditor().p)=>{
    const scope=scopeOf(p);
    return [...(scope||document).querySelectorAll(stopSelector)].some(visible);
  };
  const draft=p=>(p.value??p.innerText??"").trim();
  const found=findEditor();
  if(stopping(found.p))return "busy";
  if(!found.p)return found.state;
  if(draft(found.p))return "draft_exists";
  if(text===null)return "ready";
  const p=found.p;
  p.focus();
  if(!correctChat()||stopping(p)||draft(p))return "not_ready";
  if(!document.execCommand("insertText",false,text))return "insert_failed";
  // Allow the normal UI to render an enabled send button.
  for(let i=0;i<12;i++){
    await new Promise(r=>setTimeout(r,200));
    if(!correctChat())return "not_ready";
    const current=findEditor().p;
    if(stopping(current))return "not_ready";
    if(!current||draft(current)!==text.trim())return "draft_changed";
    const scope=current.closest("[data-composer-footer-responsive]")||current.closest("form");
    const buttons=[...(scope||document).querySelectorAll(sendSelector)]
      .filter(e=>visible(e)&&!e.disabled&&e.getAttribute("aria-disabled")!=="true");
    if(buttons.length>1)return "send_ambiguous";
    if(buttons.length===1){
      buttons[0].click();
      // Local control observations do not prove server acceptance.
      for(let j=0;j<20;j++){
        await new Promise(r=>setTimeout(r,500));
        if(!correctChat())return "wrong_chat";
        const next=findEditor().p;
        if(stopping(next))return "clicked";
        if(next&&!draft(next))return "clicked";
      }
      return "send_not_confirmed";
    }
  }
  return "send_unavailable";
}
async function inject(tabId,func,args){const r=await chrome.scripting.executeScript({target:{tabId},func,args});return r[0]?.result;}
async function poll(checkComposer=false){
 if(busy)return;busy=true;
 let s,claimed=null;
 try{
  s=await chrome.storage.local.get(["armed","url","tabId","key","status"]);
  if(!s.armed)return;
  const event=await api(s.key,"/next");
  const t=await chrome.tabs.get(s.tabId).catch(()=>null);
  if(!t?.url||new URL(t.url).origin+new URL(t.url).pathname!==s.url){
    if(event.id){const grant=await api(s.key,"/claim",{id:event.id});
    if(grant.ok)await api(s.key,"/ack",{id:event.id,status:"blocked"});}
    await chrome.storage.local.set({armed:false,pausedByOwner:false,status:"Чат закрыт или изменён. Привяжи заново."});return;
  }
  // Idle polling stays in the extension worker: never scan the long chat DOM
  // without a real result, except when the owner explicitly binds the tab.
  if(!event.id&&!checkComposer){
    const status="Связь с исполнителем есть. Ожидаю задание.";
    if(s.status!==status)await chrome.storage.local.set({status});
    return;
  }
  const state=await inject(s.tabId,composerAction,[s.url]);
  if(!event.id){await chrome.storage.local.set({status:state==="ready"?"Поле ввода найдено. Ожидаю задание.":"Проверка поля ввода: "+state});return;}
  if(!/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(event.id)||typeof event.message!=="string"||event.message.length>1200)throw Error("Invalid event");
  if(state==="busy"||state==="draft_exists"){await chrome.storage.local.set({status:"Ожидаю: "+state+" ("+event.id+")"});return;}
  if(state!=="ready"){
    const grant=await api(s.key,"/claim",{id:event.id});
    if(grant.ok)await api(s.key,"/ack",{id:event.id,status:"blocked"});
    await chrome.storage.local.set({armed:false,pausedByOwner:false,status:"Остановлено: "+state});return;
  }
  const counts=await chrome.storage.local.get(["sent"]);
  if((counts.sent||0)>=20){
    const grant=await api(s.key,"/claim",{id:event.id});
    if(grant.ok)await api(s.key,"/ack",{id:event.id,status:"blocked"});
    await chrome.storage.local.set({armed:false,pausedByOwner:false,status:"Лимит пилота: 20 сообщений. Требуется ручная проверка."});return;
  }
  if(!(await chrome.storage.local.get("armed")).armed)return;
  const grant=await api(s.key,"/claim",{id:event.id});
  if(!grant.ok)return;
  claimed=event.id;
  const current=await chrome.storage.local.get(["armed","url","tabId","key"]);
  if(!current.armed||current.url!==s.url||current.tabId!==s.tabId||current.key!==s.key){
    await api(s.key,"/ack",{id:claimed,status:"blocked"});
    await chrome.storage.local.set({armed:false,pausedByOwner:false,status:"Отправка остановлена после захвата результата. Требуется ручная проверка."});
    return;
  }
  const result=await inject(s.tabId,composerAction,[s.url,event.message]);
  await api(s.key,"/ack",{id:claimed,status:result==="clicked"?"clicked":"blocked"});
  // Never re-arm after an owner pause during an already in-flight send.
  // A completed click remains counted and cannot be replayed.
  if(result==="clicked"){
    const latest=await chrome.storage.local.get(["armed","pausedByOwner"]);
    await chrome.storage.local.set({status:latest.pausedByOwner?"Остановлено владельцем":"Нажата отправка "+claimed,sent:(counts.sent||0)+1});
  }else{
    await chrome.storage.local.set({armed:false,pausedByOwner:false,status:"Отправка не подтверждена: "+result});
  }
 }catch(e){
  if(claimed&&s?.key){try{await api(s.key,"/ack",{id:claimed,status:"blocked"});}catch{}await chrome.storage.local.set({armed:false,pausedByOwner:false,status:"Неопределённая отправка. Повтор запрещён."});}
  else await chrome.storage.local.set({status:String(e.message).slice(0,150)});
 }finally{busy=false;}
}
