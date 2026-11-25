const {launch,open,pixels,layout,restore}=require('../../../revision-r4-battery/interactive/qa/browser-tools.cjs');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const OUT=__dirname,ROOT=path.resolve(OUT,'..'),fragment=path.join(ROOT,'r5-enclosure-viewer.html');
const hash=s=>crypto.createHash('sha256').update(s).digest('hex');
const html=fs.readFileSync(fragment,'utf8'),newNote='Provisional coax to the LoRa socket · Loose tie placement and remaining cable slack to verify.',oldNote='Coax to the top LoRa socket · Transparent cut shell · Provisional cable envelope.';
const oldHash=hash(html.replace(newNote,oldNote));assert.equal(oldHash,'1c090adfca30f297958312ab47a7f1240d5a16694460a04ef8eb7b1ba5016d9f');
const priorFile=path.join(OUT,'R5-BROWSER-VALIDATION.json'),prior=JSON.parse(fs.readFileSync(priorFile,'utf8'));
prior.fragmentSha256=oldHash;prior.fragmentBytes=Buffer.byteLength(html.replace(newNote,oldNote));prior.scope='Full functional QA against preview of original R5 build; subsequent change was the coax inspection caption only. See R5-FINAL-SMOKE-VALIDATION.json.';fs.writeFileSync(priorFile,JSON.stringify(prior,null,2)+'\n');
const report={ok:false,fragmentSha256:hash(html),fragmentBytes:Buffer.byteLength(html),fullFunctionalQaSha256:oldHash,onlyChangeSinceFullQa:'Coax inspection caption clarifies unqualified tie placement and remaining cable slack.',checks:[],errors:[],screenshots:[]};
(async()=>{const run=await launch(OUT);try{
 const{page,iframe,frame}=await open(run.context,path.join(OUT,'preview.html'),report.errors);await frame.waitForFunction(()=>document.getElementById('r5-enclosure-viewer')?.dataset.ready==='true');
 for(const width of [736,320])for(const colorScheme of ['light','dark']){
  await page.setViewportSize({width,height:1500});await page.emulateMedia({colorScheme,reducedMotion:'reduce'});await restore(frame,{privateContent:{r5:{schema:1,mode:'assembled',shell:'solid',selected:'all',hidden:[],yaw:40,pitch:35,zoom:1,dimensions:'all',focus:null,overview:null}}});
  await frame.locator('[data-inspection="coax_route"]').click();await frame.waitForFunction(()=>{const d=document.getElementById('r5-enclosure-viewer').dataset;return d.focus==='coax_route'&&d.animating==='false'});assert.equal(await frame.locator('#r5-dimension-note').innerText(),newNote);const l=await layout(frame);assert(!l.overflow);for(const c of l.controls)assert(c.x>=-1&&c.x+c.width<=l.width+1);const p=await pixels(frame);assert(p.opaque>1000);assert.equal(p.error,0);assert(await frame.locator('#r5-error').isHidden());
  const file=path.join(OUT,`coax_route-${width}-${colorScheme}.png`);await iframe.screenshot({path:file});report.screenshots.push(file);report.checks.push({width,colorScheme,captionVerified:true,overflow:false,webglError:p.error});
 }
 assert.equal(report.errors.length,0);assert.equal(hash(fs.readFileSync(fragment)),report.fragmentSha256);report.ok=true;
 }finally{fs.writeFileSync(path.join(OUT,'R5-FINAL-SMOKE-VALIDATION.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));await run.close();}})().catch(e=>{console.error(e);process.exitCode=1});
