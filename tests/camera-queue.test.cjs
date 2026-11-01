// Run with npm test. Uses the actual generated portal script and IndexedDB transactions.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const {webcrypto} = require('node:crypto');
const {JSDOM} = require('jsdom');
const {IDBFactory, IDBObjectStore} = require('fake-indexeddb');
const template = execFileSync('python', ['-c', 'import app; print(app.portal_page("work", {"upload_token":"test", "name":"Test"}))'], {encoding:'utf8'});
const script = [...template.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1];
const pause = () => new Promise(resolve => setTimeout(resolve,10));
async function until(check) { for(let i=0;i<200;i++) { if(await check()) return; await pause(); } throw new Error('Condition timed out'); }
function portal({indexedDB=new IDBFactory(), online=false, token='test', response='uploaded'}={}) {
  const dom = new JSDOM(template,{url:'https://photos.example.test/work?t='+token,runScripts:'outside-only'});
  const w = dom.window, $ = id => w.document.getElementById(id);
  let connected = online, result = response, stopped = 0, sent = 0;
  Object.defineProperty(w,'isSecureContext',{value:true});
  Object.defineProperty(w,'indexedDB',{value:indexedDB});
  Object.defineProperty(w,'crypto',{value:webcrypto});
  Object.defineProperty(w.navigator,'onLine',{get:()=>connected});
  w.TextEncoder = TextEncoder; w.Blob = Blob;
  w.URL.createObjectURL = () => 'blob:test'; w.URL.revokeObjectURL = () => {};
  w.FormData = class {append() {}};
  w.ImageCapture = class {async takePhoto() {return new Blob(['captured-photo'],{type:'image/jpeg'});}};
  const track = {stop(){stopped++;},getCapabilities:()=>({}),getSettings:()=>({}),applyConstraints:async()=>{}};
  Object.defineProperty(w.navigator,'mediaDevices',{value:{getUserMedia:async()=>({getTracks:()=>[track],getVideoTracks:()=>[track]})}});
  $('camera-video').play = async()=>{};
  $('camera-dialog').showModal = function(){this.open=true;};
  $('camera-dialog').close = function(){this.open=false;this.dispatchEvent(new w.Event('close'));};
  w.XMLHttpRequest = class {
    constructor(){this.upload={};} open(){} send(){sent++; setTimeout(()=>{
      if(result==='network') return this.onerror();
      this.status = result==='uploaded' ? 200 : result==='fallback' ? 202 : 503;
      this.responseText = JSON.stringify(result==='uploaded' ? {status:'uploaded'} : result==='fallback' ? {status:'fallback'} : {detail:'Immich unavailable'});
      this.onload();
    },5);}
  };
  w.eval(`const slug='work',tok=${JSON.stringify(token)};\n`+script);
  return {dom,w,$,indexedDB,get sent(){return sent;},get stopped(){return stopped;},
    async ready(){await until(()=>$('camera-queue-status').textContent==='All camera photos uploaded.' || $('camera-queue-list').children.length>0);},
    async capture(){if(!$('camera-dialog').open) await $('open-camera').onclick(); await $('camera-shutter').onclick();},
    connect(value){connected=value;w.dispatchEvent(new w.Event(value?'online':'offline'));},
    result(value){result=value;}, close(){dom.window.close();}};
}

test('capture persists offline, survives reload and is deleted only after confirmed upload', async()=>{
  const first=portal(); try {
    await first.ready(); await first.capture(); await first.capture();
    assert.equal(first.$('camera-queue-list').children.length,2);
    assert.equal(first.sent,0);
    assert.equal(first.$('camera-shutter').disabled,false);
    first.$('camera-dialog').close(); assert.equal(first.stopped,1);
    const next=portal({indexedDB:first.indexedDB}); try {
      await next.ready(); assert.equal(next.$('camera-queue-list').children.length,2);
      next.connect(true);
      await until(()=>next.$('camera-queue-list').children.length===0);
      assert.equal(next.sent,2);
    } finally {next.close();}
  } finally {first.close();}
});

test('failed and fallback responses keep photos; manual retry clears them after confirmation', async()=>{
  for(const response of ['network','failure','fallback']) {
    const p=portal({response}); try {
      await p.ready(); await p.capture(); p.connect(true);
      await until(()=>p.$('camera-queue-list').textContent.includes(response==='network'?'interrupted':response==='fallback'?'HTTP 202':'unavailable'));
      assert.equal(p.$('camera-queue-list').children.length,1);
      p.result('uploaded'); await p.$('camera-retry').onclick();
      await until(()=>p.$('camera-queue-list').children.length===0);
      assert.equal(p.sent,2);
    } finally {p.close();}
  }
});

test('changed portal token cannot see or upload the old queue', async()=>{
  const first=portal(); try {
    await first.ready(); await first.capture();
    const other=portal({indexedDB:first.indexedDB,token:'different',online:true}); try {
      await other.ready(); assert.equal(other.sent,0); assert.equal(other.$('camera-queue-list').children.length,0);
    } finally {other.close();}
  } finally {first.close();}
});

test('two tabs coordinate one upload through the IndexedDB lease', async()=>{
  const first=portal(); try {
    await first.ready(); await first.capture();
    const second=portal({indexedDB:first.indexedDB}); try {
      await second.ready(); first.connect(true); second.connect(true);
      await until(()=>first.sent+second.sent===1); await new Promise(r=>setTimeout(r,100));
      assert.equal(first.sent+second.sent,1);
    } finally {second.close();}
  } finally {first.close();}
});

test('storage failure pauses capture and leaves a downloadable last photo', async()=>{
  const p=portal(); const original=IDBObjectStore.prototype.add;
  try {
    await p.ready();
    IDBObjectStore.prototype.add=function(){throw new Error('Quota exceeded');};
    await p.capture();
    assert.equal(p.$('camera-shutter').disabled,true);
    assert.equal(p.$('camera-last').hidden,false);
    assert.match(p.$('camera-message').textContent,/storage is unavailable or full/);
    assert.equal(p.sent,0);
  } finally {IDBObjectStore.prototype.add=original;p.close();}
});
