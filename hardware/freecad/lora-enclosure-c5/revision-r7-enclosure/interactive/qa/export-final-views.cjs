// Capture engineering illustrations only after native binding and browser QA.
const {launch,open,pixels,restore}=require('../../../revision-r4-battery/interactive/qa/browser-tools.cjs');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const ROOT=path.resolve(__dirname,'..'),OUT=path.join(ROOT,'views');
const sha=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const fragment=path.join(ROOT,'r7-enclosure-viewer.html'),build=JSON.parse(fs.readFileSync(path.join(ROOT,'BUILD-VALIDATION.json'),'utf8'));
const qa=JSON.parse(fs.readFileSync(path.join(__dirname,'R7-BROWSER-VALIDATION.json'),'utf8'));
assert(build.ok&&build.saved_native_verified&&build.native_sha256);
assert(qa.ok&&qa.saved_native_verified);assert.equal(qa.fragment_sha256,sha(fragment));assert.equal(build.sha256,sha(fragment));
assert.equal(qa.native_sha256,build.native_sha256);
assert.equal(qa.preview_sha256,sha(path.join(__dirname,'r7-preview.html')));assert(qa.preview_fragment_matches);
const report={ok:false,visual_review_pending:true,native_sha256:build.native_sha256,fragment_sha256:sha(fragment),preview_sha256:qa.preview_sha256,source_status:build.source_status,images:[],errors:[]};
(async()=>{
 const run=await launch(OUT,{viewport:{width:1024,height:1500},deviceScaleFactor:2});
 try{
  const {page,frame}=await open(run.context,path.join(__dirname,'r7-preview.html'),report.errors);
  await page.emulateMedia({colorScheme:'light',reducedMotion:'reduce'});
  await frame.waitForFunction(()=>document.getElementById('r7-enclosure-viewer')?.dataset.ready==='true');
  for(const mode of ['assembled','exploded','cutaway']){
   const state={schema:1,mode,shell:'solid',selected:'all',hidden:[],yaw:40,pitch:35,zoom:1,dimensions:mode==='cutaway'?'all':'off',focus:null,focusTarget:null,focusScale:1,overview:null};
   const before=await frame.evaluate(()=>Number(document.getElementById('r7-enclosure-viewer').dataset.drawCount));
   await restore(frame,{privateContent:{r7:state}});
   await frame.waitForFunction(n=>Number(document.getElementById('r7-enclosure-viewer').dataset.drawCount)>n,before);
   await frame.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
   const image=path.join(OUT,'R7-'+mode+'.png');const pixel=await pixels(frame);assert.equal(pixel.error,0);assert(pixel.opaque>10000);
   await frame.locator('.r7-stage').screenshot({path:image});
   const png=fs.readFileSync(image);
   report.images.push({mode,path:image,sha256:sha(image),width_px:png.readUInt32BE(16),height_px:png.readUInt32BE(20),canvas_width_px:pixel.width,canvas_height_px:pixel.height,state});
  }
  assert.equal(report.errors.length,0);report.ok=true;
 }finally{
  fs.writeFileSync(path.join(OUT,'VIEWS-VALIDATION.json'),JSON.stringify(report,null,2)+'\n');await run.close();
 }
 console.log(JSON.stringify(report));
})().catch(e=>{console.error(e);process.exitCode=1});
