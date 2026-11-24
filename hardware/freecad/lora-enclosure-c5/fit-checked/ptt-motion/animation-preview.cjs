const {chromium}=require('C:/Users/Homar/AppData/Local/OpenAI/Codex/runtimes/cua_node/5c41f77a7900391c/bin/node_modules/playwright-core');
const fs=require('node:fs'),path=require('node:path'),{pathToFileURL}=require('node:url');
const output=path.join(__dirname,'animation-preview');
fs.mkdirSync(output,{recursive:true});
const profile=fs.mkdtempSync(path.join(output,'.preview-browser-'));
const state=frame=>frame.evaluate(()=>{const r=document.getElementById('ptt-cutaway-3d');return {stroke:r.dataset.strokeMm,gap:r.dataset.gapMm,view:r.dataset.view,playing:r.dataset.playing,innerWidth,scrollWidth:document.documentElement.scrollWidth,scrollHeight:document.documentElement.scrollHeight,overflow:document.documentElement.scrollWidth>innerWidth,text:document.querySelector('[data-gap]').textContent,canvas:!!r.querySelector('canvas').getContext('webgl2'),webglError:r.querySelector('canvas').getContext('webgl2')?.getError()};});
(async()=>{
 const context=await chromium.launchPersistentContext(profile,{headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',args:['--force-color-profile=srgb'],viewport:{width:736,height:1000},deviceScaleFactor:1});
 const report=[];
 try{
  for(const width of [736,320])for(const colorScheme of ['light','dark']){
   const page=await context.newPage();await page.setViewportSize({width,height:1000});await page.emulateMedia({colorScheme});const errors=[];page.on('pageerror',e=>errors.push(String(e)));
   await page.goto(pathToFileURL(path.join(__dirname,'ptt-cutaway-animation-preview.html')).href,{waitUntil:'domcontentloaded'});
   const iframe=page.locator('#codex-visualization');const frame=await(await iframe.elementHandle()).contentFrame();await frame.waitForFunction(()=>document.getElementById('ptt-cutaway-3d')?.dataset.strokeMm!==undefined);
   await frame.evaluate(()=>document.fonts.ready);
   if(await frame.locator('[data-action=closeup]').getAttribute('aria-pressed')==='true')await frame.locator('[data-action=closeup]').click();
   await frame.locator('[data-action=released]').click();
   const results={width,colorScheme,initial:await state(frame),errors};
   results.main=path.join(output,`main-${width}-${colorScheme}.png`);await iframe.screenshot({path:results.main});
   await frame.locator('[data-action=closeup]').click();
   results.released=path.join(output,`contact-released-${width}-${colorScheme}.png`);await iframe.screenshot({path:results.released});
   await frame.locator('[data-action=pressed]').click();results.pressedState=await state(frame);
   results.pressed=path.join(output,`contact-pressed-${width}-${colorScheme}.png`);await iframe.screenshot({path:results.pressed});
   await frame.locator('input[type=range]').fill('0.125');await frame.locator('input[type=range]').dispatchEvent('change');results.scrub=await state(frame);
   if(width===736&&colorScheme==='light'){
    await frame.locator('[data-action=released]').click();await frame.locator('[data-action=play]').click();
    await frame.waitForFunction(()=>document.getElementById('ptt-cutaway-3d').dataset.strokeMm==='0.250000');results.cycleContact=await state(frame);
    await frame.waitForFunction(()=>document.getElementById('ptt-cutaway-3d').dataset.playing==='false',{},{timeout:7000});results.cycleEnd=await state(frame);
    await frame.locator('[data-action=play]').click();await frame.waitForFunction(()=>Number(document.getElementById('ptt-cutaway-3d').dataset.strokeMm)>.025);await frame.locator('[data-action=play]').click();results.paused=await state(frame);
    await frame.evaluate(()=>window.dispatchEvent(new CustomEvent('openai:set_globals',{detail:{globals:{widgetState:{privateContent:{version:1,t:.6,closeup:false}}}}})));results.restored=await state(frame);
    await page.emulateMedia({colorScheme,reducedMotion:'reduce'});await frame.locator('[data-action=released]').click();await frame.locator('[data-action=play]').click();await frame.waitForFunction(()=>document.getElementById('ptt-cutaway-3d').dataset.strokeMm==='0.250000');results.reducedContact=await state(frame);await frame.waitForFunction(()=>document.getElementById('ptt-cutaway-3d').dataset.playing==='false',{},{timeout:4000});results.reducedEnd=await state(frame);
   }
   report.push(results);await page.close();
  }
  fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
 }finally{await context.close();if(!path.resolve(profile).startsWith(path.resolve(output)+path.sep))throw Error('Profile cleanup escaped output');fs.rmSync(profile,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exit(1);});
