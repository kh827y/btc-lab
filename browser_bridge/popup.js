const key=document.getElementById("key"),status=document.getElementById("status");
const resume=document.getElementById("resume"),off=document.getElementById("off");
const ownerPaused=s=>!s.armed&&(s.pausedByOwner===true||s.status==="Остановлено владельцем");
const canResume=s=>ownerPaused(s)&&!!s.url&&Number.isInteger(s.tabId)&&
  /^[0-9a-f]{64}$/.test(s.key||"")&&(s.sent||0)<20;
async function show(){
  const s=await chrome.storage.local.get(["armed","url","status","pausedByOwner","tabId","key","sent"]);
  status.textContent=(s.armed?"Включено":"Остановлено")+"\n"+(s.url||"Чат не привязан")+"\n"+(s.status||"");
  resume.disabled=!canResume(s);
  off.disabled=!s.armed;
}
document.getElementById("arm").onclick=async()=>{
  try{
    const [t]=await chrome.tabs.query({active:true,currentWindow:true});
    const u=new URL(t.url);
    if(u.origin!=="https://chatgpt.com"||!/^\/(?:g\/[A-Za-z0-9_-]+\/)?c\/[A-Za-z0-9-]+\/?$/.test(u.pathname))throw Error("Открой именно существующий чат BTC-Lab");
    if(!/^[0-9a-f]{64}$/.test(key.value))throw Error("Вставь действующий локальный код подключения");
    await chrome.storage.local.set({armed:true,pausedByOwner:false,tabId:t.id,url:u.origin+u.pathname,key:key.value,status:"Привязан. Ожидаю локальное задание.",sent:0});
    key.value="";
    await chrome.runtime.sendMessage({action:"poll"});
    await show();
  }catch(e){status.textContent=e.message;}
};
resume.onclick=async()=>{
  try{
    const s=await chrome.storage.local.get(["armed","url","status","pausedByOwner","tabId","key","sent"]);
    if(!canResume(s))throw Error("Возобновление недоступно. Проверь причину остановки.");
    const t=await chrome.tabs.get(s.tabId).catch(()=>null);
    if(!t?.url||new URL(t.url).origin+new URL(t.url).pathname!==s.url)throw Error("Прежняя вкладка закрыта или изменена. Привяжи чат заново.");
    // Preserve the original pairing and send count. This is not a new pilot.
    await chrome.storage.local.set({armed:true,pausedByOwner:false,status:"Возобновлено. Ожидаю задание."});
    await chrome.runtime.sendMessage({action:"poll"});
    await show();
  }catch(e){status.textContent=e.message;}
};
off.onclick=async()=>{
  const s=await chrome.storage.local.get("armed");
  if(s.armed)await chrome.storage.local.set({armed:false,pausedByOwner:true,status:"Остановлено владельцем"});
  await show();
};
show();
chrome.storage.onChanged.addListener((changes,area)=>{if(area==="local"&&(changes.status||changes.armed||changes.url||changes.pausedByOwner||changes.sent))show();});
