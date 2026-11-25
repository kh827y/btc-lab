// BTC Lab: only dispatch trusted main workflow; no repository writes here.
const BTC_REPO = 'kh827y/btc-lab';
const BTC_INBOX = '1jWyD2KkLxTBbrfWYOe5v4PE8chVLzrmI';
const BTC_PROCESSED = '1OuFijX_OKdbithL-vmIvWvykvK3GCDJA';
const BTC_ID = /^[a-z0-9][a-z0-9-]{5,63}$/;
const BTC_SENT = 'BTC_SYNC_DISPATCHED:';

function installBtcSync() {
  const token = PropertiesService.getScriptProperties().getProperty('BTC_GITHUB_TOKEN');
  if (!token) throw Error('Set BTC_GITHUB_TOKEN in Script properties first');
  for (const t of ScriptApp.getProjectTriggers()) {
    if (['pollBtcSync', 'cleanBtcSync'].includes(t.getHandlerFunction())) ScriptApp.deleteTrigger(t);
  }
  ScriptApp.newTrigger('pollBtcSync').timeBased().everyMinutes(1).create();
  ScriptApp.newTrigger('cleanBtcSync').timeBased().everyDays(1).create();
  pollBtcSync();
}

function pollBtcSync() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) return;
  try {
    const token = PropertiesService.getScriptProperties().getProperty('BTC_GITHUB_TOKEN');
    if (!token) throw Error('Missing BTC_GITHUB_TOKEN');
    const folder = DriveApp.getFolderById(BTC_INBOX);
    const files = folder.getFiles();
    while (files.hasNext()) {
      const f = files.next();
      const name = f.getName();
      if (!name.endsWith('.ready.json') || (f.getDescription() || '').startsWith(BTC_SENT)) continue;
      const job = name.slice(0, -'.ready.json'.length);
      if (!BTC_ID.test(job) || f.getSize() > 65536) continue;
      let m;
      try { m = JSON.parse(f.getBlob().getDataAsString('UTF-8')); } catch (_) { continue; }
      if (!m || m.schema !== 1 || m.job_id !== job || !/^[0-9a-f]{40}$/.test(m.base_sha) || !/^[0-9a-f]{40}$/.test(m.head_sha) || !/^[0-9a-f]{64}$/.test(m.sha256)) continue;
      const matches = folder.getFilesByName(job + '.bundle');
      if (!matches.hasNext()) continue;
      const bundle = matches.next();
      if (matches.hasNext() || bundle.getSize() > 25 * 1024 * 1024 || bundle.getSize() === 0) continue;
      const same = folder.getFilesByName(name);
      same.next();
      if (same.hasNext()) continue;
      const r = UrlFetchApp.fetch('https://api.github.com/repos/' + BTC_REPO + '/actions/workflows/btc-drive-import.yml/dispatches', {
        method: 'post', contentType: 'application/json',
        headers: {Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'},
        payload: JSON.stringify({ref: 'main', inputs: {job_id: job}}), muteHttpExceptions: true
      });
      if (r.getResponseCode() < 200 || r.getResponseCode() >= 300) throw Error('GitHub dispatch HTTP ' + r.getResponseCode());
      f.setDescription(BTC_SENT + new Date().toISOString());
      console.log('Dispatched ' + job);
      break; // one dispatch per minute
    }
  } finally { lock.releaseLock(); }
}

function cleanBtcSync() {
  const folder = DriveApp.getFolderById(BTC_PROCESSED);
  const files = folder.getFiles();
  const cutoff = Date.now() - 7 * 86400000;
  while (files.hasNext()) {
    const f = files.next();
    if (/^[a-z0-9][a-z0-9-]{5,63}\.(bundle|ready\.json)$/.test(f.getName()) && f.getDateCreated().getTime() < cutoff) f.setTrashed(true);
  }
}
