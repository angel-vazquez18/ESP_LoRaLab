// Focused GPU/material and interaction QA for selected PTT parts and forces.
const {chromium}=require('C:/Users/Homar/AppData/Local/OpenAI/Codex/runtimes/cua_node/5c41f77a7900391c/bin/node_modules/playwright-core');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{pathToFileURL}=require('node:url');
const output=path.join(__dirname,'highlight-preview');fs.mkdirSync(output,{recursive:true});
const profile=fs.mkdtempSync(path.join(output,'.preview-browser-'));
const report={checks:[],errors:[],screenshots:[]},record=(name,detail={})=>report.checks.push({name,...detail});
const ids=['flange','stop_cup','nuts','screws','lid'];
const meshIds=JSON.parse(fs.readFileSync(path.join(__dirname,'ptt-cutaway-meshes.json'),'utf8')).parts.map(p=>p.id);
const meshMap={flange:['plunger'],stop_cup:['stop_cup'],nuts:['left_nut','right_nut'],screws:['left_screw','right_screw'],lid:['lid']};
const kinds={flange:['flange_on_cup'],stop_cup:['flange_on_cup','cup_on_nut'],nuts:['cup_on_nut','nut_on_screw'],screws:['nut_on_screw','head_on_lid','lid_on_screw'],lid:['head_on_lid','lid_on_screw']};
const expectedForces=id=>['left','right'].flatMap(side=>kinds[id].map(kind=>`${side}_${kind}`)).sort();
const select=(frame,id)=>frame.locator(`button[data-part="${id}"]`).click();
const press=(frame,action)=>frame.locator(`[data-action="${action}"]`).click();
const setCamera=(frame,yaw,pitch,zoom=1)=>frame.evaluate(values=>{for(const [key,value]of Object.entries(values)){const input=document.getElementById('ptt-camera-'+key);input.value=String(value);input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));}},{yaw,pitch,zoom});
const state=frame=>frame.evaluate(()=>{const root=document.getElementById('ptt-cutaway-3d'),gl=root.querySelector('canvas').getContext('webgl2');return {data:{...root.dataset},arrows:[...root.querySelectorAll('[data-force-id]')].map(el=>({id:el.dataset.forceId,highlighted:el.dataset.highlighted,related:el.parentElement.dataset.related,strokeWidth:getComputedStyle(el).strokeWidth,stroke:getComputedStyle(el).stroke,opacity:getComputedStyle(el.parentElement).opacity,worldStart:el.dataset.worldStart,worldEnd:el.dataset.worldEnd})),forceDisplay:getComputedStyle(root.querySelector('[data-force-overlay]')).display,overflow:document.documentElement.scrollWidth>innerWidth,webglError:gl.getError(),depthTest:gl.isEnabled(gl.DEPTH_TEST),depthWrite:gl.getParameter(gl.DEPTH_WRITEMASK),blend:gl.isEnabled(gl.BLEND)};});
function checkSelection(s,id,engaged){
 assert.equal(s.data.selectedPart,id);assert.deepEqual(JSON.parse(s.data.highlightedMeshes).sort(),[...meshMap[id]].sort());
 assert.deepEqual(JSON.parse(s.data.highlightedForceIds).sort(),engaged?expectedForces(id):[]);
 if(id==='flange')assert.deepEqual(JSON.parse(s.data.highlightedFlangeLocalBounds),[22.4,23.6]);
 assert.equal(s.data.forceVisible,String(engaged));assert.equal(s.overflow,false);assert.equal(s.webglError,0);assert(s.depthTest&&s.depthWrite&&!s.blend);
 if(!engaged){assert.equal(s.forceDisplay,'none');return;}
 for(const arrow of s.arrows){const related=expectedForces(id).includes(arrow.id);assert.equal(arrow.highlighted,String(related));assert.equal(arrow.related,String(related));assert.equal(Number.parseFloat(arrow.strokeWidth),related?2.8:1.2);const start=JSON.parse(arrow.worldStart),end=JSON.parse(arrow.worldEnd);assert(Math.abs(end[0]-start[0])<1e-8&&Math.abs(end[1]-start[1])<1e-8);assert(Math.abs(end[2]-start[2]-(arrow.id.endsWith('lid_on_screw')?2.1:-2.1))<1e-8);}
}
async function installTrace(frame){await frame.evaluate(()=>{
 const canvas=document.querySelector('#ptt-cutaway-3d canvas'),gl=canvas.getContext('webgl2'),program=gl.getParameter(gl.CURRENT_PROGRAM),vaoIds=new WeakMap();let nextId=1;
 const locations=Object.fromEntries(['uSelectionMode','uEdgePass','uUseTint','uDz','uClipMinZ'].map(name=>[name,gl.getUniformLocation(program,name)]));
 window.__highlightShaders=gl.getAttachedShaders(program).map(shader=>gl.getShaderSource(shader));
 const readTrace=(method,args)=>{
  const vao=gl.getParameter(gl.VERTEX_ARRAY_BINDING);if(!vaoIds.has(vao))vaoIds.set(vao,nextId++);
  const uniforms=Object.fromEntries(Object.entries(locations).map(([name,location])=>[name,location?gl.getUniform(program,location):null]));
  let tint=null;
  if(uniforms.uUseTint){const previous=gl.getParameter(gl.ARRAY_BUFFER_BINDING),location=gl.getAttribLocation(program,'aTint'),buffer=gl.getVertexAttrib(location,gl.VERTEX_ATTRIB_ARRAY_BUFFER_BINDING);gl.bindBuffer(gl.ARRAY_BUFFER,buffer);const values=new Float32Array(gl.getBufferParameter(gl.ARRAY_BUFFER,gl.BUFFER_SIZE)/4);gl.getBufferSubData(gl.ARRAY_BUFFER,0,values);gl.bindBuffer(gl.ARRAY_BUFFER,previous);let hash=2166136261;for(const byte of new Uint8Array(values.buffer))hash=Math.imul(hash^byte,16777619)>>>0;tint={hash,alphas:[...new Set(values.filter((_,i)=>i%4===3))].sort(),vertices:values.length/4};}
  window.__highlightTrace.push({method,mode:args[0],count:method==='drawArrays'?args[2]:args[1],vao:vaoIds.get(vao),uniforms,tint,depthTest:gl.isEnabled(gl.DEPTH_TEST),depthWrite:gl.getParameter(gl.DEPTH_WRITEMASK),blend:gl.isEnabled(gl.BLEND)});
 };
 for(const method of ['drawElements','drawArrays']){const original=gl[method].bind(gl);gl[method]=function(...args){if(window.__highlightTraceEnabled)readTrace(method,args);return original(...args);};}
 });}
const trace=frame=>frame.evaluate(()=>{window.__highlightTrace=[];window.__highlightTraceEnabled=true;document.getElementById('ptt-camera-yaw').dispatchEvent(new Event('input',{bubbles:true}));window.__highlightTraceEnabled=false;return window.__highlightTrace;});
const pixels=frame=>frame.evaluate(()=>{
 const root=document.getElementById('ptt-cutaway-3d'),canvas=root.querySelector('canvas'),gl=canvas.getContext('webgl2'),program=gl.getParameter(gl.CURRENT_PROGRAM),matrix=gl.getUniform(program,gl.getUniformLocation(program,'uViewProjection')),image=new Uint8Array(canvas.width*canvas.height*4);gl.readPixels(0,0,canvas.width,canvas.height,gl.RGBA,gl.UNSIGNED_BYTE,image);let hash=2166136261;for(const byte of image)hash=Math.imul(hash^byte,16777619)>>>0;
 const stroke=Number(root.dataset.strokeMm),points={flange:[55.5,9,23-stroke],shaft:[51,9,26-stroke],foot:[51,9,19-stroke],stop_cup:[55.5,9,21.15],left_nut:[40.4,9,19.35],right_nut:[61.6,9,19.35],left_screw:[42,9,25.1],right_screw:[60,9,25.1],lid:[63,9,25.8]},samples={};
 for(const [name,p]of Object.entries(points)){const x=matrix[0]*p[0]+matrix[4]*p[1]+matrix[8]*p[2]+matrix[12],y=matrix[1]*p[0]+matrix[5]*p[1]+matrix[9]*p[2]+matrix[13],px=Math.floor((x+1)*canvas.width/2),py=Math.floor((y+1)*canvas.height/2),offset=(py*canvas.width+px)*4;samples[name]={point:p,pixel:[px,py],rgba:[...image.subarray(offset,offset+4)]};}
 return {hash,width:canvas.width,height:canvas.height,samples};
});
function checkGpu(trace,id,partByVao,transparent=false){
 const opaque=trace.filter(call=>call.mode===4&&!call.uniforms.uUseTint&&!call.uniforms.uEdgePass),selected=[];
 for(const call of opaque){const part=partByVao[call.vao];assert(part,'Unknown opaque mesh VAO');const expected=meshMap[id].includes(part)?id==='flange'?2:1:0;assert.equal(call.uniforms.uSelectionMode,expected,`Wrong GPU selection for ${part}`);if(expected)selected.push(part);}
 if(!transparent)assert.deepEqual([...new Set(selected)].sort(),[...meshMap[id]].sort());
 const edges=trace.filter(call=>call.mode===1);assert(edges.length>0,'Selected model has no geometric edge draw');assert(edges.every(call=>call.uniforms.uEdgePass&&call.count>0),'Missing edge shader pass');
 return {selectedOpaqueMeshes:[...new Set(selected)],edgeCalls:edges.length,edgeVertices:edges.reduce((sum,call)=>sum+call.count,0)};
}
(async()=>{
 const context=await chromium.launchPersistentContext(profile,{headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',args:['--force-color-profile=srgb'],viewport:{width:736,height:1300},deviceScaleFactor:1});
 try{
  const page=await context.newPage();page.on('pageerror',error=>report.errors.push(String(error)));await page.emulateMedia({colorScheme:'light'});await page.goto(pathToFileURL(path.join(__dirname,'ptt-cutaway-animation-preview.html')).href,{waitUntil:'domcontentloaded'});
  const iframe=page.locator('#codex-visualization'),frame=await(await iframe.elementHandle()).contentFrame();await frame.waitForFunction(()=>document.getElementById('ptt-cutaway-3d')?.dataset.highlightedMeshes);
  await installTrace(frame);await press(frame,'pressed');await setCamera(frame,0,0,1);
  const initialTrace=await trace(frame),opaqueVaos=[...new Set(initialTrace.filter(call=>call.mode===4&&!call.uniforms.uUseTint&&!call.uniforms.uEdgePass).map(call=>call.vao))];assert.equal(opaqueVaos.length,meshIds.length);const partByVao=Object.fromEntries(opaqueVaos.map((vao,i)=>[vao,meshIds[i]]));
  const sources=await frame.evaluate(()=>window.__highlightShaders);assert(sources.some(source=>source.includes('vLocalZ')&&source.includes('22.39999')&&source.includes('23.60001')),'Actual shader is missing flange local-Z bounds');record('actual shader uses local flange band',{bounds:[22.4,23.6],boundaryEpsilon:0.00001});
  const selections={};for(const id of ids){await select(frame,id);const s=await state(frame),gpuTrace=await trace(frame);checkSelection(s,id,true);selections[id]=await pixels(frame);record(`opaque ${id} mesh and force selection`,{state:s,gpu:checkGpu(gpuTrace,id,partByVao),pixels:selections[id]});await setCamera(frame,17,15,1);const file=path.join(output,`selected-${id}-736-light.png`);await iframe.screenshot({path:file});report.screenshots.push(file);await setCamera(frame,0,0,1);}
  for(const id of ids)assert.notEqual(selections[id].hash,selections[ids[(ids.indexOf(id)+1)%ids.length]].hash,'Selection produced no canvas pixel difference');
  for(const sample of ['shaft','foot'])assert.deepEqual(selections.flange.samples[sample].rgba,selections.lid.samples[sample].rgba,`Flange highlight spills into ${sample}`);
  assert.notDeepEqual(selections.flange.samples.flange.rgba,selections.lid.samples.flange.rgba,'Flange surface pixel did not highlight');
  for(const [id,samples]of Object.entries({stop_cup:['stop_cup'],nuts:['left_nut','right_nut'],screws:['left_screw','right_screw'],lid:['lid']}))for(const sample of samples)assert.notDeepEqual(selections[id].samples[sample].rgba,selections.flange.samples[sample].rgba,`${id} material pixel did not highlight`);
  record('actual canvas pixels change only in the selected flange band or parts',{selectionHashes:Object.fromEntries(ids.map(id=>[id,selections[id].hash])),flange:selections.flange.samples,comparison:selections.lid.samples});
  await select(frame,'flange');await press(frame,'closeup');const closeup=path.join(output,'selected-flange-closeup-736-light.png');await iframe.screenshot({path:closeup});report.screenshots.push(closeup);record('isolated flange-band close-up',{data:(await state(frame)).data});await press(frame,'closeup');await setCamera(frame,0,0,1);
  await select(frame,'flange');for(const stroke of [0,.125,.249,.25]){await frame.locator('#ptt-3d-stroke').fill(String(stroke));await frame.locator('#ptt-3d-stroke').dispatchEvent('change');const s=await state(frame);checkSelection(s,'flange',stroke===.25);const calls=(await trace(frame)).filter(call=>call.uniforms.uSelectionMode===2);assert(calls.length>0);assert(calls.every(call=>Math.abs(call.uniforms.uDz+stroke)<1e-6));record(`moving flange highlight and force gate ${stroke} mm`,{data:s.data,selectedCalls:calls.length});}
  await page.emulateMedia({colorScheme:'dark'});await setCamera(frame,17,15,1);await press(frame,'pressed');await frame.locator('#ptt-transparent-shell').check();const transparent={};
  for(const id of ['stop_cup','lid']){await select(frame,id);const s=await state(frame),calls=await trace(frame);checkSelection(s,id,true);checkGpu(calls,id,partByVao,true);const tinted=calls.filter(call=>call.uniforms.uUseTint);assert.equal(tinted.length,1);assert(tinted[0].blend&&tinted[0].depthTest&&!tinted[0].depthWrite);assert.deepEqual(tinted[0].tint.alphas.map(x=>Number(x.toFixed(2))),[.14,.24]);transparent[id]={tint:tinted[0].tint,pixels:await pixels(frame)};const file=path.join(output,`selected-${id}-transparent-736-dark.png`);await iframe.screenshot({path:file});report.screenshots.push(file);record(`transparent ${id} highlight and original opacity`,{state:s,tint:tinted[0].tint});}
  assert.notEqual(transparent.stop_cup.tint.hash,transparent.lid.tint.hash,'Transparent tint cache did not update on selection');assert.notEqual(transparent.stop_cup.pixels.hash,transparent.lid.pixels.hash,'Transparent selection did not change canvas pixels');record('transparent tint cache changes on label selection',transparent);
  await page.setViewportSize({width:320,height:1300});await select(frame,'nuts');let s=await state(frame);checkSelection(s,'nuts',true);const mobile=path.join(output,'selected-nuts-transparent-320-dark.png');await iframe.screenshot({path:mobile});report.screenshots.push(mobile);record('mobile selected parts and arrows fit',{data:s.data});
  await frame.locator('#ptt-playback-speed').selectOption('2');await press(frame,'released');await press(frame,'play');await frame.waitForFunction(()=>Number(document.getElementById('ptt-cutaway-3d').dataset.strokeMm)>.01);const before=await state(frame);await select(frame,'screws');const after=await state(frame);assert.equal(after.data.playing,'true');for(const key of ['yaw','pitch','zoom','view','speed'])assert.equal(after.data[key],before.data[key]);assert.notEqual(after.data.cycleTime,before.data.cycleTime);record('highlight selection preserves looping and camera',{before:before.data,after:after.data});
  await frame.waitForFunction(()=>document.getElementById('ptt-cutaway-3d').dataset.forceVisible==='true');s=await state(frame);checkSelection(s,'screws',true);record('selected force arrows highlight during contact dwell',{data:s.data});await frame.waitForFunction(()=>document.getElementById('ptt-cutaway-3d').dataset.forceVisible==='false');s=await state(frame);checkSelection(s,'screws',false);assert.equal(s.data.playing,'true');record('force highlights disappear on release while part stays selected',{data:s.data});
  assert.equal(report.errors.length,0);record('no JavaScript or WebGL errors');await page.close();
 }catch(error){report.failure=String(error.stack||error);throw error;}finally{fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({checks:report.checks.map(item=>item.name),errors:report.errors,failure:report.failure,screenshots:report.screenshots},null,2));await context.close();if(!path.resolve(profile).startsWith(path.resolve(output)+path.sep))throw Error('Preview profile escaped output directory');fs.rmSync(profile,{recursive:true,force:true});}
})().catch(error=>{console.error(error);process.exit(1)});
