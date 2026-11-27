import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const root=path.dirname(fileURLToPath(import.meta.url));
const sha=async p=>crypto.createHash('sha256').update(await fs.readFile(p)).digest('hex');
const baselinePath=path.join(root,'../../final-design/bom/complete-bom.json');
const uploadPath=path.join(root,'../craftcloud/upload-manifest.json');
const baseline=JSON.parse(await fs.readFile(baselinePath,'utf8'));
const upload=JSON.parse(await fs.readFile(uploadPath,'utf8'));
const rowByRef=new Map(baseline.map(r=>[r.Reference,{...r}]));
const update=(ref,fields)=>Object.assign(rowByRef.get(ref),fields);
const fields=['Reference','Item','Specification','Qty per unit','Unit','Qty for build','Assembly note','Source'];
const printedMap={'CASE_BASE':'enclosure-base','CASE_LID':'enclosure-lid','PTT_PLUNGER':'ptt-plunger','PTT_CUP':'ptt-stop-cup'};
const bounds=part=>upload.files.find(r=>r.part===part).dimensions_mm.map(n=>n.toFixed(2)).join(' x ');
for(const [ref,part] of Object.entries(printedMap))update(ref,{
 Specification:bounds(part)+' mm; unfilled MJF PA12',
 'Assembly note':`C5-R4-${part}-mm.stl. `+({CASE_BASE:'Eight M3 inserts total: four top, four rear.',CASE_LID:'R3 fit retained. Nominal OLED gap 0.50 mm.',PTT_PLUNGER:'Shaft dia 8.0 mm. Verify free sliding.',PTT_CUP:'Provisional stop travel 0.25 mm. Verify actual switch.'}[ref]),
 Source:'R4 native CAD and validated Craftcloud upload manifest'
});
update('CASE_INSERT',{'Qty per unit':8,'Qty for build':8,'Assembly note':'Four top + four rear. OD 5 x length 4 mm. Pilot dia 4.4; top depth 5.0, rear depth 4.5 mm. Do not count twice.'});
update('U3',{'Assembly note':'USB supply retained. Battery-only use requires verified speaker-disabled firmware with AMP_SD LOW.'});
const make=(Reference,Item,Specification,qty,Unit,note,Source)=>({Reference,Item,Specification,'Qty per unit':qty,Unit,'Qty for build':qty,'Assembly note':note,Source});
const material='R4 native CAD and validated Craftcloud upload manifest';
const hardware='R4 HARDWARE-ADDENDUM.txt and native clearance audit';
const battery='https://meshnology.com/collections/frontpage/products/3-7v-3000mah-rechargeable-battery-for-arduino-esp32; user product dimension image';
const additions=[
 make('BAT_COVER','Battery back cover',bounds('battery-cover')+' mm; unfilled MJF PA12',1,'part','C5-R4-battery-cover-mm.stl. Rounded guides and two strap paths. Cover floor 2.4 mm, local channels 1 mm deep.',material),
 make('BAT_SCREW','Rear cover screw','M3 x 6 button head; ISO 7380 compatible',4,'piece','3.6 mm nominal engagement. 0.9 mm tip clearance. Do not substitute M3 x 8 into the blind holes.',hardware),
 make('BAT1','Meshnology 103665 LiPo','3.7 V nominal, 3000 mAh; 68 x 36 x 10 mm reserved',1,'pack','Photo body 68 x 35 x 10 mm; verify actual maximum. Heltec BAT only. Verify keyed plug/polarity and permissible charge current.',battery),
 make('BAT_STRAP','Soft nonconductive strap','10 mm wide; about 160 mm starting length',2,'piece','Trim to actual path and overlap. Retain without squeezing pouch; check strap thickness in available clearance.',hardware),
 make('BAT_PAD','Insulating support pad','About 36 x 68 mm; up to 1 mm thick',1,'piece','Select cell-compatible, nonconductive soft material. No sharp edges or rigid compression of the pouch.',hardware),
 make('BAT_EXT','Conditional battery lead extension','Matched two-pin housing; verified end-to-end polarity',0,'piece','Optional, excluded from default quantity. Set per-unit qty to 1 only if the 66 mm supplied lead lacks service slack. Verify USB coexistence.', 'R4 BATTERY-CONNECTION-REVIEW.txt; actual connector must be checked'),
 make('RF_ASSEMBLY','External antenna and coax','Matched to Heltec RF connector and operating band',1,'set','Existing external assembly retained. Exact antenna, connector and coax length are not supplied; select against owned hardware.', 'C5 enclosure assembly notes: external antenna and coax passage'),
 make('USB_LEAD','USB cable and power source','Compatible Heltec USB-C lead and rated supply',1,'set','External service item, not stored in case. Amplifier requires USB. Confirm low-profile overmould fits alongside battery plug.', 'C5 USB-powered architecture; R4 connector-fit review')
];
const rows=[rowByRef.get('CASE_BASE'),rowByRef.get('CASE_LID'),rowByRef.get('PTT_PLUNGER'),rowByRef.get('PTT_CUP'),additions[0],
 rowByRef.get('CASE_SCREW'),additions[1],rowByRef.get('CASE_INSERT'),rowByRef.get('CUP_SCREW'),rowByRef.get('CUP_NUT'),rowByRef.get('WIRE_TIE'),
 ...additions.slice(2,6),...baseline.slice(9).map(r=>rowByRef.get(r.Reference)),...additions.slice(6)];
if(rows.length!==28||new Set(rows.map(r=>r.Reference)).size!==28)throw Error('BOM identity count mismatch');
const wb=Workbook.create(),sheet=wb.worksheets.add('Complete BOM');
sheet.showGridLines=false;sheet.tabColor='#23496A';
const first=7,last=first+rows.length-1,end=42;
sheet.getRange(`A1:H${end}`).format.font={name:'Arial',size:10,color:'#243447'};
sheet.getRange('A2').values=[['LoRa C5-R4 complete assembly BOM']];sheet.getRange('A2').format.font={size:15,bold:true};
sheet.getRange('A3').values=[['Battery compartment and Heltec BAT connection. Amplifier remains USB-powered. Prototype fit checks remain.']];
sheet.getRange('A4').values=[['Build qty']];sheet.getRange('B4').values=[[1]];
sheet.getRange('B4').format.fill='#FFF1BD';sheet.getRange('B4').dataValidation={rule:{type:'whole',operator:'between',formula1:1,formula2:1000}};
sheet.getRange('A6:F6').values=[['Reference','Item','Specification','Per unit','Unit','Build qty']];sheet.getRange('H6').values=[['Assembly notes']];
sheet.getRange(`A${first}:H${last}`).values=rows.map(r=>[r.Reference,r.Item,r.Specification,r['Qty per unit'],r.Unit,null,'',r['Assembly note']]);
sheet.getRange(`F${first}`).formulas=[[`=D${first}*$B$4`]];sheet.getRange(`F${first}:F${last}`).fillDown();
sheet.getRange('A6:F6').format={fill:'#23496A',font:{bold:true,color:'#FFFFFF'},rowHeight:28,horizontalAlignment:'center',verticalAlignment:'center'};
sheet.getRange('H6').format.font={bold:true};
sheet.getRange(`A${first}:F${last}`).format={rowHeight:58,verticalAlignment:'center',wrapText:true};
sheet.getRange(`H${first}:H${last}`).format={wrapText:true,verticalAlignment:'center'};
sheet.getRange(`D${first}:D${last}`).setNumberFormat('0');sheet.getRange(`F${first}:F${last}`).setNumberFormat('0');
sheet.getRange(`D${first}:D${last}`).format.horizontalAlignment='right';sheet.getRange(`F${first}:F${last}`).format.horizontalAlignment='right';
for(const [col,width] of Object.entries({A:110,B:185,C:285,D:65,E:64,F:74,G:22,H:450}))sheet.getRange(`${col}1:${col}${end}`).format.columnWidthPx=width;
for(let i=0;i<rows.length;i++)wb.notes.add({id:`source-${i}`,target:{cell:{sheetName:sheet.name,sheetId:sheet.sheetId,address:`C${i+first}`}},authorId:'',createdAt:'',body:{plainText:`Source: ${rows[i].Source}`}});
const notes=[
 'Five printed parts. Eight M3 inserts total: four for the lid and four for the battery cover.',
 'BAT_EXT is conditional and excluded from the default order. Exact antenna/coax and USB hardware remain to be selected.',
 'Module support heights remain reference values: Heltec 5 mm; microphone and amplifier 3 mm. Verify actual headers.',
 'PTT 0.25 mm stop travel and OLED 0.50 mm nominal gap need physical verification. No extra loose module spacers are specified.',
 'Normal audio firmware enables the unpowered amplifier without USB. Use a verified speaker-disabled Heltec build for battery-only operation.',
 'Confirm battery connector polarity/keying, simultaneous USB fit and permissible charge current before connection or charging.',
 'No purchase made. Sources are notes on specification cells; the CSV contains their full text.'
];
notes.forEach((v,i)=>sheet.getRange(`A${36+i}`).values=[[v]]);
sheet.getRange('A36:H42').format.font={size:10,color:'#536573'};
sheet.freezePanes.freezeRows(6);
wb.recalculate();
for(const qty of [2,3,1]){
 sheet.getRange('B4').values=[[qty]];wb.recalculate();
 if(sheet.getRange(`D${first}:F${last}`).values.some(r=>r[2]!==qty*r[0]))throw Error('Build quantity scaling failed');
}
const extRow=first+rows.findIndex(r=>r.Reference==='BAT_EXT');
sheet.getRange(`D${extRow}`).values=[[1]];wb.recalculate();
if(sheet.getRange(`F${extRow}`).values[0][0]!==1)throw Error('Conditional extension selection failed');
sheet.getRange(`D${extRow}`).values=[[0]];wb.recalculate();
const values=sheet.getRange(`A${first}:H${last}`).values;
if(values.some(r=>r[3]!==r[5]))throw Error('Quantity restoration failed');
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:50}});
await fs.writeFile(path.join(root,'bom-formula-scan.json'),errors.ndjson);
const inspect=await wb.inspect({kind:'table',range:`'Complete BOM'!A6:F${last}`,include:'values,formulas',tableMaxRows:30,tableMaxCols:6});
await fs.writeFile(path.join(root,'bom-inspection.ndjson'),inspect.ndjson);
for(const [name,range] of [['complete-bom-upper','A1:H15'],['complete-bom-middle','A16:H27'],['complete-bom-lower','A28:H42']]){
 const png=await wb.render({sheetName:sheet.name,range,scale:1,format:'png'});
 await fs.writeFile(path.join(root,name+'.png'),new Uint8Array(await png.arrayBuffer()));
}
const output=await SpreadsheetFile.exportXlsx(wb);await output.save(path.join(root,'LoRa-C5-R4-Complete-BOM.xlsx'));
const quote=v=>'"'+String(v??'').replaceAll('"','""')+'"';
await fs.writeFile(path.join(root,'LoRa-C5-R4-Complete-BOM.csv'),'\ufeff'+[fields,...rows.map(r=>fields.map(f=>r[f]))].map(r=>r.map(quote).join(',')).join('\r\n')+'\r\n');
await fs.writeFile(path.join(root,'complete-bom.json'),JSON.stringify(rows,null,2)+'\n');
const validation={ok:false,rows:28,uniqueReferences:28,printedParts:5,closureScrewsM3x22:4,rearScrewsM3x6:4,totalM3Inserts:8,pttCupScrews:2,pttCupNuts:2,batteryPacks:1,batteryStraps:2,pad:1,conditionalExtensionDefault:0,speakerWirePairRows:1,quantityScaleAndRestorePassed:true,conditionalExtensionSelectionPassed:true,visualReview:'pending',sourceHashes:{baselineCompleteBOM:await sha(baselinePath),R4UploadManifest:await sha(uploadPath)},files:{xlsx:await sha(path.join(root,'LoRa-C5-R4-Complete-BOM.xlsx')),csv:await sha(path.join(root,'LoRa-C5-R4-Complete-BOM.csv'))}};
await fs.writeFile(path.join(root,'BOM-VALIDATION.json'),JSON.stringify(validation,null,2)+'\n');
console.log(JSON.stringify(validation));
