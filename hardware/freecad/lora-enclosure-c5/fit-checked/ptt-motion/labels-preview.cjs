// Focused clickable-label QA against the actual cutaway projection and motion.
const {chromium}=require('C:/Users/Homar/AppData/Local/OpenAI/Codex/runtimes/cua_node/5c41f77a7900391c/bin/node_modules/playwright-core');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{pathToFileURL}=require('node:url');
const output=path.join(__dirname,'labels-preview');fs.mkdirSync(output,{recursive:true});
const profile=fs.mkdtempSync(path.join(output,'.preview-browser-'));
const stateOnly=process.argv.includes('--state-only');
const report=stateOnly?JSON.parse(fs.readFileSync(path.join(output,'report.json'),'utf8')):{checks:[],errors:[],screenshots:[]};delete report.failure;
const record=(name,detail={})=>report.checks.push({name,...detail});
const ids=['flange','stop_cup','nuts','screws','lid'];
const labels={flange:'Flange',stop_cup:'Stop cup',nuts:'Nuts',screws:'Screws',lid:'Lid'};
const anchors={flange:[55.5,9,22.9],stop_cup:[55.5,9,21.15],nuts:[61.6,9,19.35],screws:[60,9,24.3],lid:[63,9,25.8]};
const press=(frame,action)=>frame.locator(`[data-action="${action}"]`).click();
const setCamera=(frame,yaw,pitch,zoom=1)=>frame.evaluate(({yaw,pitch,zoom})=>{for(const [key,value]of Object.entries({yaw,pitch,zoom})){const el=document.getElementById('ptt-camera-'+key);el.value=String(value);el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));}},{yaw,pitch,zoom});
const state=frame=>frame.evaluate(()=>{
 const r=document.getElementById('ptt-cutaway-3d'),canvas=r.querySelector('canvas'),gl=canvas.getContext('webgl2'),program=gl.getParameter(gl.CURRENT_PROGRAM),rect=canvas.getBoundingClientRect();
 const box=el=>{const b=el.getBoundingClientRect();return {x:b.x,y:b.y,width:b.width,height:b.height};};
 const visibility=el=>{for(let p=el;p;p=p.parentElement){const s=getComputedStyle(p);if(s.display==='none'||s.visibility==='hidden')return false;}return true;};
 return {data:{...r.dataset},canvas:{width:rect.width,height:rect.height},matrix:[...gl.getUniform(program,gl.getUniformLocation(program,'uViewProjection'))],
  buttons:[...r.querySelectorAll('button[data-part]')].map(el=>({id:el.dataset.part,tag:el.tagName,text:el.textContent,pressed:el.getAttribute('aria-pressed'),visible:visibility(el),box:box(el)})),
  markers:[...r.querySelectorAll('g[data-part-marker]')].map(el=>({id:el.dataset.partMarker,data:{...el.dataset},visible:visibility(el),circle:{cx:el.querySelector('circle')?.getAttribute('cx'),cy:el.querySelector('circle')?.getAttribute('cy'),r:el.querySelector('circle')?.getAttribute('r'),stroke:el.querySelector('circle')&&getComputedStyle(el.querySelector('circle')).stroke,strokeWidth:el.querySelector('circle')&&getComputedStyle(el.querySelector('circle')).strokeWidth},path:el.querySelector('path')?.getAttribute('d')})),
  detail:{text:r.querySelector('#ptt-part-detail')?.textContent,live:r.querySelector('#ptt-part-detail')?.getAttribute('aria-live')},
  overflow:document.documentElement.scrollWidth>innerWidth,innerWidth,webglError:gl.getError()};
});
function project(s,p){const m=s.matrix,w=m[3]*p[0]+m[7]*p[1]+m[11]*p[2]+m[15];return [(m[0]*p[0]+m[4]*p[1]+m[8]*p[2]+m[12])/w*s.canvas.width/2+s.canvas.width/2,s.canvas.height/2-(m[1]*p[0]+m[5]*p[1]+m[9]*p[2]+m[13])/w*s.canvas.height/2];}
function checkSelection(s,id){
 assert.equal(s.data.selectedPart,id);assert.equal(s.buttons.length,5);assert.deepEqual(s.buttons.map(b=>b.id).sort(),[...ids].sort());
 for(const b of s.buttons){assert.equal(b.tag,'BUTTON');assert.equal(b.pressed,String(b.id===id));assert(b.visible);assert(b.box.width>0&&b.box.height>0);}
 assert.equal(s.detail.live,'polite');assert(s.detail.text.toLowerCase().includes(labels[id].toLowerCase()),'Selected name missing from explanation');assert(s.detail.text.length>50,'Explanation missing');
 assert.equal(s.overflow,false);assert.equal(s.webglError,0);
}
function checkLayout(s){
 for(const b of s.buttons){assert(b.box.x>=-1&&b.box.x+b.box.width<=s.innerWidth+1,`Button clipped: ${b.id}`);}
 for(let i=0;i<s.buttons.length;i++)for(let j=i+1;j<s.buttons.length;j++){const a=s.buttons[i].box,b=s.buttons[j].box;assert(a.x+a.width<=b.x+.1||b.x+b.width<=a.x+.1||a.y+a.height<=b.y+.1||b.y+b.height<=a.y+.1,'Part label buttons overlap');}
}
function checkProjection(s){
 assert.equal(s.markers.length,5);let maxError=0;
 for(const m of s.markers){const world=JSON.parse(m.data.worldAnchor),screen=JSON.parse(m.data.screenAnchor),expected=[...anchors[m.id]];if(m.id==='flange')expected[2]-=Number(s.data.strokeMm);
  for(let i=0;i<3;i++)assert(Math.abs(world[i]-expected[i])<2e-6,`Wrong ${m.id} material anchor`);
  const projected=project(s,world);for(let i=0;i<2;i++){const error=Math.abs(screen[i]-projected[i]);maxError=Math.max(maxError,error);assert(error<.1,`Leader not attached to GPU projection: ${m.id}`);}
  if(m.visible){assert(m.data.inView==='true');assert(Math.abs(Number(m.circle.cx)-screen[0])<.1&&Math.abs(Number(m.circle.cy)-screen[1])<.1,'Marker circle differs from projected anchor');if(s.innerWidth>580)assert(m.path,'Visible desktop marker lacks leader');}
 }
 return {maxProjectionErrorPx:maxError};
}
(async()=>{
 const context=await chromium.launchPersistentContext(profile,{headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',args:['--force-color-profile=srgb'],viewport:{width:736,height:1250},deviceScaleFactor:1});
 try{
  const page=await context.newPage();page.on('pageerror',e=>report.errors.push(String(e)));await page.emulateMedia({colorScheme:'dark'});await page.goto(pathToFileURL(path.join(__dirname,'ptt-cutaway-animation-preview.html')).href,{waitUntil:'domcontentloaded'});
  const iframe=page.locator('#codex-visualization'),frame=await(await iframe.elementHandle()).contentFrame();await frame.waitForFunction(()=>document.getElementById('ptt-cutaway-3d')?.dataset.selectedPart);
  let s;
  if(!stateOnly){
  s=await state(frame);checkSelection(s,'flange');checkLayout(s);record('five native labels with default flange explanation',s);
  for(const id of ids){await frame.locator(`button[data-part="${id}"]`).click();s=await state(frame);checkSelection(s,id);record(`click selects ${id}`,{selected:s.data.selectedPart,detail:s.detail});}
  await frame.locator('button[data-part="flange"]').focus();await page.keyboard.press('Enter');checkSelection(await state(frame),'flange');await frame.locator('button[data-part="nuts"]').focus();await page.keyboard.press('Space');checkSelection(await state(frame),'nuts');record('keyboard Enter and Space activate labels');
  for(const stroke of [0,.125,.25]){await frame.locator('#ptt-3d-stroke').fill(String(stroke));await frame.locator('#ptt-3d-stroke').dispatchEvent('change');s=await state(frame);record(`material anchors track ${stroke} mm stroke`,{projection:checkProjection(s),data:s.data});}
  for(const [yaw,pitch,zoom]of [[17,15,1],[155,30,1.3],[30,-45,1],[45,25,8]]){await setCamera(frame,yaw,pitch,zoom);s=await state(frame);record(`camera projection ${yaw} ${pitch} ${zoom}`,{projection:checkProjection(s),markers:s.markers});}
  for(const [width,colorScheme]of [[736,'dark'],[320,'light']]){
   await page.setViewportSize({width,height:1250});await page.emulateMedia({colorScheme});await setCamera(frame,17,15,1);if((await state(frame)).data.view==='contact')await press(frame,'closeup');await press(frame,'pressed');await frame.locator('button[data-part="screws"]').click();s=await state(frame);checkSelection(s,'screws');checkLayout(s);checkProjection(s);
   if(width===320){assert(s.markers.filter(x=>x.visible).every(x=>x.id==='screws'));assert(s.markers.find(x=>x.id==='screws').visible,'Selected mobile marker hidden');}else assert.equal(s.markers.filter(x=>x.visible).length,5,'Desktop leaders incomplete');
   const file=path.join(output,`labels-contact-${width}-${colorScheme}.png`);await iframe.screenshot({path:file});report.screenshots.push(file);record(`responsive labels ${width} ${colorScheme}`,s);
  }
  await page.setViewportSize({width:736,height:1250});await frame.locator('#ptt-playback-speed').selectOption('2');await press(frame,'released');await press(frame,'play');await frame.waitForFunction(()=>Number(document.getElementById('ptt-cutaway-3d').dataset.strokeMm)>.01);
  const before=await state(frame);await frame.locator('button[data-part="lid"]').click();const after=await state(frame);checkSelection(after,'lid');assert.equal(after.data.playing,'true');for(const k of ['yaw','pitch','zoom','view','speed'])assert.equal(after.data[k],before.data[k],`Part selection changed ${k}`);assert.notEqual(after.data.cycleTime,before.data.cycleTime,'Animation did not advance during label click');record('label selection preserves looping and camera',{before:before.data,after:after.data});
  await frame.locator('button[data-part="stop_cup"]').focus();await page.keyboard.press('Enter');s=await state(frame);checkSelection(s,'stop_cup');assert.equal(s.data.playing,'true');record('keyboard selection while animation plays',{data:s.data,detail:s.detail});
  await press(frame,'play');
  }else await frame.locator('button[data-part="stop_cup"]').click();
  const saved=await frame.evaluate(()=>window.openai.widgetState);assert.equal(saved.privateContent.version,5);assert.equal(saved.privateContent.selectedPart,'stop_cup');assert.equal(saved.modelContent.selected_load_part,'stop_cup');record('selection persisted in version 5 snapshot',saved);
  await frame.locator('button[data-part="flange"]').click();await frame.evaluate(saved=>{saved.privateContent.origin='external-qa';window.dispatchEvent(new CustomEvent('openai:set_globals',{detail:{globals:{widgetState:saved}}}));},saved);s=await state(frame);checkSelection(s,'stop_cup');assert.equal(s.data.playing,'false');record('external state restores selected part',s.data);
  const older=JSON.parse(JSON.stringify(saved));older.privateContent.version=4;older.privateContent.origin='external-qa-v4';delete older.privateContent.selectedPart;delete older.modelContent.selected_load_part;await frame.evaluate(saved=>window.dispatchEvent(new CustomEvent('openai:set_globals',{detail:{globals:{widgetState:saved}}})),older);s=await state(frame);checkSelection(s,'flange');record('version 4 restores with default flange',s.data);
  await frame.evaluate(()=>window.dispatchEvent(new CustomEvent('openai:set_globals',{detail:{globals:{widgetState:{modelContent:{depression_mm:.25,flange_gap_mm:0,view:'complete mechanism',selected_load_part:'nuts'}}}}})));s=await state(frame);checkSelection(s,'nuts');record('model-only state restores label selection',s.data);
  assert.equal(report.errors.length,0);record('no JavaScript or WebGL errors');await page.close();
 }catch(error){report.failure=String(error.stack||error);throw error;}finally{fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({checks:report.checks.map(x=>x.name),errors:report.errors,failure:report.failure,screenshots:report.screenshots},null,2));await context.close();if(!path.resolve(profile).startsWith(path.resolve(output)+path.sep))throw Error('Profile escaped output directory');fs.rmSync(profile,{recursive:true,force:true});}
})().catch(error=>{console.error(error);process.exit(1)});
