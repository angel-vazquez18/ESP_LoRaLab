// Targeted regression for disabling the guide exactly as the motion loop wraps.
const {chromium}=require('C:/Users/Homar/AppData/Local/OpenAI/Codex/runtimes/cua_node/5c41f77a7900391c/bin/node_modules/playwright-core');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{pathToFileURL}=require('node:url');
const output=path.join(__dirname,'guided-preview'),profile=fs.mkdtempSync(path.join(output,'.preview-browser-'));
const report={errors:[]};
(async()=>{
 const context=await chromium.launchPersistentContext(profile,{headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',viewport:{width:736,height:1300}});
 try{
  const page=await context.newPage();page.on('pageerror',error=>report.errors.push(String(error)));await page.goto(pathToFileURL(path.join(__dirname,'ptt-cutaway-animation-preview.html')).href,{waitUntil:'domcontentloaded'});
  const frame=await(await page.locator('#codex-visualization').elementHandle()).contentFrame();await frame.waitForFunction(()=>document.getElementById('ptt-cutaway-3d')?.dataset.guidedMode!==undefined);
  report.before=await frame.evaluate(()=>{
   window.dispatchEvent(new CustomEvent('openai:set_globals',{detail:{globals:{widgetState:{privateContent:{version:6,origin:'external-boundary-qa',guided:true,selectedPart:'flange',t:0,cycleTime:4290,speed:1,guideElapsed:6500,guideSawContact:true,closeup:false,transparentShell:false}}}}}));
   window.__qaOriginalRAF=window.requestAnimationFrame;window.requestAnimationFrame=()=>-1;
   document.querySelector('[data-action="play"]').click();return {...document.getElementById('ptt-cutaway-3d').dataset};
  });
  assert.equal(report.before.guidedMode,'true');assert.equal(report.before.playing,'true');assert.equal(report.before.selectedPart,'flange');assert.equal(Number(report.before.cycleTime),4290);
  await new Promise(resolve=>setTimeout(resolve,35));
  report.after=await frame.evaluate(()=>{const guide=document.getElementById('ptt-guided-mode');guide.checked=false;guide.dispatchEvent(new Event('change',{bubbles:true}));const root=document.getElementById('ptt-cutaway-3d');return {data:{...root.dataset},checked:guide.checked,glError:root.querySelector('canvas').getContext('webgl2').getError(),saved:window.openai.widgetState};});
  assert.equal(report.after.data.selectedPart,'flange');assert.equal(report.after.data.guidedMode,'false');assert.equal(report.after.data.playing,'true');assert.equal(report.after.checked,false);assert(Number(report.after.data.cycleTime)<1000,'Loop did not wrap during guide disable');assert.equal(report.after.glError,0);assert.equal(report.after.saved.privateContent.selectedPart,'flange');assert.equal(report.after.saved.privateContent.guided,false);assert.equal(report.errors.length,0);
  report.passed=true;report.name='disabling guide at loop boundary preserves selected part and playback';
  await frame.evaluate(()=>{document.querySelector('[data-action="play"]').click();window.requestAnimationFrame=window.__qaOriginalRAF;delete window.__qaOriginalRAF;});await page.close();
 }catch(error){report.failure=String(error.stack||error);throw error;}finally{fs.writeFileSync(path.join(output,'boundary-report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));await context.close();if(!path.resolve(profile).startsWith(path.resolve(output)+path.sep))throw Error('Profile escaped output directory');fs.rmSync(profile,{recursive:true,force:true});}
})().catch(error=>{console.error(error);process.exit(1)});
