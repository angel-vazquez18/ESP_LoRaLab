// Shared browser QA helpers. No production geometry or UI mutation.
const {chromium}=require('C:/Users/Homar/AppData/Local/OpenAI/Codex/runtimes/cua_node/5c41f77a7900391c/bin/node_modules/playwright-core');
const fs=require('node:fs'),path=require('node:path');
const {pathToFileURL}=require('node:url');
async function launch(output,options={}) {
  fs.mkdirSync(output,{recursive:true});
  const profile=fs.mkdtempSync(path.join(output,'.preview-browser-'));
  const context=await chromium.launchPersistentContext(profile,{
    headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    args:['--force-color-profile=srgb'],viewport:{width:736,height:1500},deviceScaleFactor:1,...options,
  });
  return {context,async close(){
    await context.close();
    const resolved=path.resolve(profile),root=path.resolve(output)+path.sep;
    if(!resolved.startsWith(root))throw Error('Preview profile escaped QA directory');
    fs.rmSync(resolved,{recursive:true,force:true});
  }};
}
async function open(context,file,errors) {
  const page=await context.newPage();
  page.on('pageerror',error=>errors.push(String(error)));
  await page.goto(pathToFileURL(path.resolve(file)).href,{waitUntil:'domcontentloaded'});
  const iframe=page.locator('#codex-visualization');await iframe.waitFor();
  const frame=await(await iframe.elementHandle()).contentFrame();
  await frame.locator('canvas').first().waitFor({state:'attached'});
  await frame.evaluate(()=>document.fonts.ready);
  return {page,iframe,frame};
}
async function pixels(frame) {
  return frame.evaluate(()=>{
    const canvas=document.querySelector('canvas'),gl=canvas.getContext('webgl2');
    if(!gl)return {webgl:false};
    const rgba=new Uint8Array(canvas.width*canvas.height*4);gl.readPixels(0,0,canvas.width,canvas.height,gl.RGBA,gl.UNSIGNED_BYTE,rgba);
    let opaque=0,hash=2166136261;
    for(let i=0;i<rgba.length;i+=4){
      if(rgba[i+3]>10)opaque++;
      hash=Math.imul(hash^rgba[i],16777619);hash=Math.imul(hash^rgba[i+1],16777619);
      hash=Math.imul(hash^rgba[i+2],16777619);hash=Math.imul(hash^rgba[i+3],16777619);
    }
    return {webgl:true,width:canvas.width,height:canvas.height,opaque,hash:hash>>>0,error:gl.getError()};
  });
}
async function layout(frame) {
  return frame.evaluate(()=>({
    width:innerWidth,scrollWidth:document.documentElement.scrollWidth,
    overflow:document.documentElement.scrollWidth>innerWidth,
    controls:[...document.querySelectorAll('button,select,input')].filter(e=>e.getBoundingClientRect().width).map(e=>{
      const b=e.getBoundingClientRect();return {id:e.id,type:e.type,role:e.getAttribute('role'),text:e.innerText||e.getAttribute('aria-label'),x:b.x,y:b.y,width:b.width,height:b.height};
    }),
    text:document.body.innerText,
  }));
}
const restore=(frame,saved)=>frame.evaluate(saved=>window.dispatchEvent(new CustomEvent('openai:set_globals',{detail:{globals:{widgetState:saved}}})),saved);
module.exports={launch,open,pixels,layout,restore};
