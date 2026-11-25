import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';
import {fileURLToPath,pathToFileURL} from 'node:url';
const root=path.dirname(fileURLToPath(import.meta.url));
// Windows policy disallows a node_modules junction here. Resolve the public
// package entry from the bundled Node runtime without changing dependencies.
const requireRuntime=createRequire(path.resolve(path.dirname(process.execPath),'..','codex-runtime-entry.mjs'));
const {Workbook,SpreadsheetFile}=await import(pathToFileURL(requireRuntime.resolve('@oai/artifact-tool')).href);
const sha=async p=>crypto.createHash('sha256').update(await fs.readFile(p)).digest('hex');
const rows=JSON.parse(await fs.readFile(path.join(root,'R7-complete-bom.json'),'utf8'));
const wb=Workbook.create(),s=wb.worksheets.add('R7 assembly BOM');
s.showGridLines=false;s.tabColor='#23496A';
const start=7,end=start+rows.length-1;
s.getRange(`A1:J${end}`).format.font={name:'Arial',size:10,color:'#243447'};
s.getRange('A2').values=[['R7 BOM']];s.getRange('A2').format.font={size:15,bold:true};
s.getRange('C2').values=[['LoRa C5 assembly']];s.getRange('C2').format.font={size:15,bold:true};
s.getRange('A3:C3').values=[['7 print parts','PCB unchanged','Optional coupon defaults to zero']];
s.getRange('A4').values=[['Build quantity']];s.getRange('B4').values=[[1]];
s.getRange('B4').format.fill='#FFF1BD';s.getRange('B4').dataValidation={rule:{type:'whole',operator:'between',formula1:1,formula2:1000}};
s.getRange('H2').values=[['Assembly notes']];s.getRange('H2').format.font={size:14,bold:true};
s.getRange('H3').values=[['Read R7-ASSEMBLY-AND-INSPECTION.txt for full fit and commissioning requirements.']];
s.getRange('H4').values=[['Quantity zero marks an optional item. No purchase has been made.']];
s.getRange('A6:F6').values=[['Reference','Item','Specification','Per unit','Unit','Build qty']];
s.getRange('H6').values=[['Fit / procurement note']];s.getRange('J6').values=[['Source']];
s.getRange(`A${start}:F${end}`).values=rows.map(r=>[r.Reference,r.Item,r.Specification,r['Qty per unit'],r.Unit,null]);
s.getRange(`F${start}`).formulas=[[`=D${start}*$B$4`]];s.getRange(`F${start}:F${end}`).fillDown();
const concise={
 CASE_BASE:'Eight M3 inserts total: four main lid and four battery cover.',CASE_LID:'Retain nominal OLED gap 0.50 mm; no glass pressure.',
 PTT_PLUNGER:'Verify actual shaft sliding and switch travel.',PTT_CUP:'0.25 mm switch depression remains provisional.',BAT_COVER:'Use M3x6 screws; no longer substitution.',
 FIT_COUPON:'Optional process sample, not installed; set per-unit quantity to 1 if required.',
 LS1:'One 8-ohm / 1-W speaker; connector removed; validate actual frame and power limit.',
 RF_ASSEMBLY:'Measure fixed rear hex, thread length and coax; kit nut/washer already included.',
 U3:'Existing USB power retained; battery-only commissioning issue remains separate.',
 BAT1:'Heltec BAT only; check actual pack size, keyed polarity and permitted charge current.',
 BAT_EXT:'Conditional extension only if owned lead lacks service slack; verify end-to-end polarity.',
 USB_LEAD:'External service item; amplifier needs USB. Check plug coexistence.',
 SPEAKER_RETAINER:'Seat at both hard stops; 1.4 mm bearing roof and M2x12 hardware.',
 SMA_KEY:'Provisional 8 AF fixed rear hex. Trial-fit key before batch ordering.'
};
for(let i=0;i<rows.length;i++){
 const r=rows[i],n=start+i;
 let note=concise[r.Reference]??r['Assembly note'];
 if(note.length>124)note=note.slice(0,95).trimEnd()+'... See full CSV/fit guide.';
 s.getRange(`H${n}`).values=[[note]];
 s.getRange(`J${n}`).values=[[r.Source]];
}
s.getRange('A6:F6').format={fill:'#23496A',font:{bold:true,color:'#FFFFFF'},rowHeight:28,horizontalAlignment:'center',verticalAlignment:'center'};
s.getRange('H6').format.font={bold:true};s.getRange('J6').format.font={bold:true};
s.getRange(`A${start}:F${end}`).format={rowHeight:44,verticalAlignment:'center',wrapText:true};
s.getRange(`H${start}:J${end}`).format={verticalAlignment:'center',wrapText:false};
s.getRange(`D${start}:D${end}`).setNumberFormat('0');s.getRange(`F${start}:F${end}`).setNumberFormat('0');
s.getRange(`D${start}:D${end}`).format.horizontalAlignment='right';s.getRange(`F${start}:F${end}`).format.horizontalAlignment='right';
s.getRange(`E${start}:E${end}`).format.horizontalAlignment='center';
for(const[col,w]of Object.entries({A:142,B:198,C:320,D:65,E:68,F:76,G:24,H:700,I:24,J:1100}))s.getRange(`${col}1:${col}${end}`).format.columnWidthPx=w;
for(let i=0;i<rows.length;i++)if(rows[i]['Qty per unit']===0)s.getRange(`D${start+i}`).format.fill='#FFF1BD';
s.freezePanes.freezeRows(6);s.freezePanes.freezeColumns(2);
wb.recalculate();
for(const quantity of [3,1]){
 s.getRange('B4').values=[[quantity]];wb.recalculate();
 if(s.getRange(`D${start}:F${end}`).values.some(r=>r[2]!==quantity*r[0]))throw Error('Build quantity calculation');
}
const couponRow=start+rows.findIndex(r=>r.Reference==='FIT_COUPON');
s.getRange(`D${couponRow}`).values=[[1]];wb.recalculate();if(s.getRange(`F${couponRow}`).values[0][0]!==1)throw Error('Coupon inclusion');
s.getRange(`D${couponRow}`).values=[[0]];wb.recalculate();
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:50}});
await fs.writeFile(path.join(root,'BOM-FORMULA-SCAN.ndjson'),errors.ndjson);
const inspection=await wb.inspect({kind:'table',range:`'R7 assembly BOM'!A6:F${end}`,include:'values,formulas',tableMaxRows:40,tableMaxCols:6});
await fs.writeFile(path.join(root,'BOM-INSPECTION.ndjson'),inspection.ndjson);
for(const [name,range]of[['upper','A1:F18'],['middle','A19:F31'],['lower','A32:F43'],['notes','H1:J18']]){
 const img=await wb.render({sheetName:s.name,range,scale:1,format:'png'});await fs.writeFile(path.join(root,'BOM-'+name+'.png'),new Uint8Array(await img.arrayBuffer()));
}
await(await SpreadsheetFile.exportXlsx(wb)).save(path.join(root,'LoRa-C5-R7-Complete-BOM.xlsx'));
const fields=['Reference','Item','Specification','Qty per unit','Unit','Qty for build','Assembly note','Source','Group'];
const quote=x=>'"'+String(x??'').replaceAll('"','""')+'"';
await fs.writeFile(path.join(root,'LoRa-C5-R7-Complete-BOM.csv'),'\ufeff'+[fields,...rows.map(r=>fields.map(f=>r[f]))].map(r=>r.map(quote).join(',')).join('\r\n')+'\r\n');
const report={ok:false,rows:rows.length,unique_references:new Set(rows.map(r=>r.Reference)).size,default_installed_prints:rows.filter(r=>r.Group==='Printed part').reduce((n,r)=>n+r['Qty per unit'],0),optional_coupon_default:0,pcb_modified:false,build_quantity_test:true,coupon_enable_restore_test:true,visual_review_pending:true,source_hashes:{[path.join(root,'R7-complete-bom.json')]:await sha(path.join(root,'R7-complete-bom.json'))},files:{xlsx:await sha(path.join(root,'LoRa-C5-R7-Complete-BOM.xlsx')),csv:await sha(path.join(root,'LoRa-C5-R7-Complete-BOM.csv'))}};
if(report.default_installed_prints!==7||report.unique_references!==37)throw Error('BOM quantity/reference error');
await fs.writeFile(path.join(root,'BOM-VALIDATION.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));
