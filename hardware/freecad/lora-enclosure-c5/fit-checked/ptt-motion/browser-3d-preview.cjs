// Local HTML preview using the already-installed Codex runtime and Edge.
// Usage: node browser-preview.cjs wrapper.html [output-directory]
// Probe only: node browser-preview.cjs --probe
const {chromium}=require('C:/Users/Homar/AppData/Local/OpenAI/Codex/runtimes/cua_node/5c41f77a7900391c/bin/node_modules/playwright-core');
const fs=require('node:fs');
const path=require('node:path');
const {pathToFileURL}=require('node:url');

(async()=>{
  const input=process.argv[2];
  if(!input) throw new Error('Supply a local HTML path or --probe');
  const probe=input==='--probe';
  const output=path.resolve(process.argv[3] || __dirname);
  fs.mkdirSync(output,{recursive:true});
  const profile=fs.mkdtempSync(path.join(output,'.preview-browser-'));
  const context=await chromium.launchPersistentContext(profile,{headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',args:['--force-color-profile=srgb'],viewport:{width:736,height:1000},deviceScaleFactor:1});
  const browser=context.browser();
  const results=[];
  try {
    for(const width of [736,320]) for(const colorScheme of ['light','dark']) {
      const page=await context.newPage();
      await page.setViewportSize({width,height:1000});
      await page.emulateMedia({colorScheme});
      const errors=[];
      page.on('pageerror',e=>errors.push(String(e)));
      if(probe) await page.setContent('<!doctype html><title>Local preview check</title><style>body{margin:0;font:16px sans-serif;color:CanvasText;background:Canvas;color-scheme:light dark}</style><p>Browser preview ready</p>');
      else await page.goto(pathToFileURL(path.resolve(input)).href,{waitUntil:'domcontentloaded'});
      await page.evaluate(()=>document.fonts.ready);
      const metrics=await page.evaluate(()=>({title:document.title,innerWidth,scrollWidth:document.documentElement.scrollWidth,scrollHeight:document.documentElement.scrollHeight,dark:matchMedia('(prefers-color-scheme: dark)').matches,horizontalOverflow:document.documentElement.scrollWidth>innerWidth}));
      let frameMetrics=null;
      let capture=page;
      if(!probe) {
        const iframe=page.locator('#codex-visualization');
        await iframe.waitFor();
        const frame=await (await iframe.elementHandle()).contentFrame();
        await frame.locator('canvas').first().waitFor({state:'attached'});
        await frame.evaluate(()=>document.fonts.ready);
        frameMetrics=await frame.evaluate(()=>({innerWidth,scrollWidth:document.documentElement.scrollWidth,scrollHeight:document.documentElement.scrollHeight,dark:matchMedia('(prefers-color-scheme: dark)').matches,horizontalOverflow:document.documentElement.scrollWidth>innerWidth,svgCount:document.querySelectorAll('svg').length,bodyText:document.body.innerText}));
        capture=iframe;
      }
      const screenshot=probe ? undefined : path.join(output,`preview-${width}-${colorScheme}.png`);
      const bytes=(await capture.screenshot({path:screenshot,animations:'disabled'})).length;
      results.push({width,colorScheme,screenshot,bytes,metrics,frameMetrics,errors});
      await page.close();
    }
    const report={browser:browser.version(),mode:probe?'probe':'local-html',results};
    if(!probe) fs.writeFileSync(path.join(output,'browser-preview-report.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify(report,null,2));
  } finally {
    await context.close();
    const resolvedProfile=path.resolve(profile);
    if(!resolvedProfile.startsWith(path.resolve(output)+path.sep)) throw new Error('Preview profile escaped output directory');
    fs.rmSync(resolvedProfile,{recursive:true,force:true});
  }
})().catch(e=>{console.error(e);process.exit(1)});
