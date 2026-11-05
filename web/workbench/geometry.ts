// Bench geometry in millimetres. Y is up; parts stand on the bench (y = 0) or on a breadboard.
import type {Layout} from '../types';
import type {PartSpec,PartState,Placement,Target} from './types';

export const PITCH=2.54;
export const BOARD_TOP=1.6;          // PCB thickness
export const BREADBOARD_TOP=8.5;     // breadboard surface height

export const BB_COLUMNS:Record<string,number>={full:63,half:30,mini:17};
// Row centre lines (z) relative to the breadboard origin at hole e1.
export const BB_ROWS:Record<string,number>={
 tp:-17.78,tn:-15.24,a:-10.16,b:-7.62,c:-5.08,d:-2.54,e:0,f:7.62,g:10.16,h:12.7,i:15.24,j:17.78,bp:22.86,bn:25.4,
};
export const STRIP_ROWS=['a','b','c','d','e','f','g','h','i','j'];
export const RAIL_ROWS=['tp','tn','bp','bn'];

export function breadboardHoles(size:string){
 const columns=BB_COLUMNS[size]??63;
 const rows=size==='mini'?STRIP_ROWS:[...RAIL_ROWS,...STRIP_ROWS];
 const holes:{name:string;x:number;z:number}[]=[];
 for(const row of rows)for(let c=1;c<=columns;c++)holes.push({name:`${row}${c}`,x:(c-1)*PITCH,z:BB_ROWS[row]});
 return holes;
}
export function breadboardBox(size:string){
 const columns=BB_COLUMNS[size]??63,rails=size!=='mini';
 return {x0:-PITCH*1.5,x1:(columns-1)*PITCH+PITCH*1.5,z0:rails?-21:-13,z1:rails?29:21};
}

export function rotate([dx,dz]:[number,number],rot:number):[number,number]{
 switch(((rot%4)+4)%4){case 1:return[-dz,dx];case 2:return[-dx,-dz];case 3:return[dz,-dx];default:return[dx,dz];}
}

export function partPins(spec:PartSpec,placement:Partial<Placement>):Record<string,[number,number]>{
 const out:Record<string,[number,number]>={};
 const x=placement.x??0,z=placement.z??0,rot=placement.rot??0;
 spec.pins.forEach((pin,i)=>{
  const [dx,dz]=rotate(spec.footprint[i]??[i,0],rot);
  out[pin]=[x+dx*PITCH,z+dz*PITCH];
 });
 return out;
}

export interface HoleIndex {find(x:number,z:number):{board:string;hole:string;x:number;z:number;y:number}|null}

export function holeIndex(parts:PartState[]):HoleIndex{
 const boards=parts.filter(p=>p.type==='breadboard');
 return {find(x,z){
  for(const b of boards){
   const bx=b.placement.x??0,bz=b.placement.z??0,size=String(b.props.size??'full');
   const col=Math.round((x-bx)/PITCH)+1,columns=BB_COLUMNS[size]??63;
   if(col<1||col>columns)continue;
   const dz=z-bz;
   for(const [row,rz] of Object.entries(BB_ROWS)){
    if(size==='mini'&&RAIL_ROWS.includes(row))continue;
    if(Math.abs(dz-rz)<1.1&&Math.abs(x-bx-(col-1)*PITCH)<1.1)
     return {board:b.id,hole:`${row}${col}`,x:bx+(col-1)*PITCH,z:bz+rz,y:BREADBOARD_TOP};
   }
  }
  return null;
 }};
}

// -- target boards -------------------------------------------------------------------
export const ALS_SCALE=0.2;            // SVG px -> mm (1440 x 1040 px board = 288 x 208 mm)
export const ALS_ORIGIN:[number,number]=[-300,-104];
export function alsPoint(px:number,py:number):[number,number]{return[ALS_ORIGIN[0]+px*ALS_SCALE,ALS_ORIGIN[1]+py*ALS_SCALE];}
export const ALS_POWER_TAP:[string,number,number][]=[['3V3',1190,300],['5V',1215,300],['GND',1240,300]];

export function alsHeaderPins(layout:Layout,header:string):[number,number][]{
 const [cx,cy]=layout.headers[header];
 const vertical=layout.headerOrientations[header]==='vertical';
 return Array.from({length:10},(_,p)=>{
  let dx=-23.5+Math.floor(p/2)*12,dy=-4.5+(p%2)*10;
  if(vertical)[dx,dy]=[-dy,dx];
  return alsPoint(cx+dx,cy+dy);
 });
}

export const MBED_LEFT=['GND','VIN','VB','nR','p5','p6','p7','p8','p9','p10','p11','p12','p13','p14','p15','p16','p17','p18','p19','p20'];
export const MBED_RIGHT=['VOUT','VU','IF-','IF+','RD+','RD-','TD-','TD+','D-','D+','p30','p29','p28','p27','p26','p25','p24','p23','p22','p21'];
export const MBED_WIRABLE=new Set(['GND','VOUT','VU',...Array.from({length:26},(_,i)=>`p${i+5}`)]);
export const MBED_ORIGIN:[number,number]=[-80,0];
export function mbedPins():{name:string;x:number;z:number}[]{
 const pins:{name:string;x:number;z:number}[]=[];
 MBED_LEFT.forEach((name,i)=>pins.push({name,x:MBED_ORIGIN[0]-24.13+i*PITCH,z:MBED_ORIGIN[1]-11.43}));
 MBED_RIGHT.forEach((name,i)=>pins.push({name,x:MBED_ORIGIN[0]-24.13+i*PITCH,z:MBED_ORIGIN[1]+11.43}));
 return pins;
}

export const BARE_PADS:string[]=(()=>{
 const pads:string[]=[];
 const ranges:[number,number[]][]=[[0,[...Array.from({length:12},(_,i)=>i),15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30]],
  [1,[0,1,4,8,9,10,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31]],[2,Array.from({length:14},(_,i)=>i)],[3,[25,26]],[4,[28,29]]];
 for(const [port,list] of ranges)for(const pin of list)pads.push(`P${port}.${pin}`);
 return pads;
})();
export const BARE_ORIGIN:[number,number]=[-70,0];
export function barePins():{name:string;x:number;z:number}[]{
 const all=['3V3','GND',...BARE_PADS,'GND','3V3'];
 const half=Math.ceil(all.length/2);
 return all.map((name,i)=>{
  const row=i<half?0:1,index=row?i-half:i;
  return {name,x:BARE_ORIGIN[0]-(half-1)*PITCH/2+index*PITCH,z:BARE_ORIGIN[1]+(row?18:-18)};
 });
}

export function targetEndpoints(target:Target,layout:Layout,headers:string[]){
 const out:{endpoint:string;x:number;z:number;y:number;label:string}[]=[];
 if(target==='als'){
  for(const h of headers)alsHeaderPins(layout,h).forEach(([x,z],i)=>out.push({endpoint:`kit.${h}.${i+1}`,x,z,y:BOARD_TOP+2.5,label:`${h}.${i+1}`}));
  for(const [name,px,py] of ALS_POWER_TAP){const [x,z]=alsPoint(px,py);out.push({endpoint:`kit.${name}`,x,z,y:BOARD_TOP+2.5,label:name});}
 }else if(target==='mbed'){
  for(const p of mbedPins())if(MBED_WIRABLE.has(p.name))out.push({endpoint:`mbed.${p.name}`,x:p.x,z:p.z,y:BOARD_TOP+9,label:p.name});
 }else{
  barePins().forEach(p=>out.push({endpoint:`mcu.${p.name}`,x:p.x,z:p.z,y:BOARD_TOP+2.5,label:p.name}));
 }
 return out;
}
