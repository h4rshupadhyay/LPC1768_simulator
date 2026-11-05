// Procedural 3D models for catalogue parts. Units: mm. Each body is drawn relative to the
// part's first pin and rotated by its quarter-turn placement; pins land on breadboard holes.
import {useEffect,useMemo,useRef} from 'react';
import {useFrame,useThree} from '@react-three/fiber';
import * as THREE from 'three';
import type {PartSpec,PartState} from './types';
import {PITCH,rotate} from './geometry';

const BAND=['#111','#7a3b12','#d22','#f07a1a','#f2d21b','#2a8b2a','#2357c9','#7b3fb3','#888','#f4f4f4'];
const LED_COLORS:Record<string,string>={red:'#ff3b2f',yellow:'#ffd21f',orange:'#ff8a1f',green:'#3dff5a',blue:'#3d7bff',white:'#f4f7ff',ir:'#5a1a2a'};

export function resistorBands(ohms:number){
 let value=Math.max(1,Math.round(ohms)),exp=0;
 while(value>=100){value=Math.round(value/10);exp++;}
 const digits=String(value).padStart(2,'0');
 return [BAND[+digits[0]],BAND[+digits[1]],exp<10?BAND[exp]:BAND[9],'#c9a227'];
}

export function useCanvasTexture(width:number,height:number,draw:(ctx:CanvasRenderingContext2D)=>void,deps:unknown[]){
 const invalidate=useThree(s=>s.invalidate);
 const texture=useMemo(()=>{
  const canvas=document.createElement('canvas');canvas.width=width;canvas.height=height;
  const t=new THREE.CanvasTexture(canvas);t.colorSpace=THREE.SRGBColorSpace;t.anisotropy=4;return t;
 },[width,height]);
 useEffect(()=>{
  const ctx=(texture.image as HTMLCanvasElement).getContext('2d')!;
  draw(ctx);texture.needsUpdate=true;invalidate();
 // eslint-disable-next-line react-hooks/exhaustive-deps
 },deps);
 useEffect(()=>()=>texture.dispose(),[texture]);
 return texture;
}

function Pcb({w,d,color='#1c5a9c',y=3,children}:{w:number;d:number;color?:string;y?:number;children?:React.ReactNode}){
 return <group position={[0,y,0]}>
  <mesh castShadow receiveShadow><boxGeometry args={[w,1.6,d]}/><meshStandardMaterial color={color} roughness={.7}/></mesh>
  {children}
 </group>;
}

function Pins({spec,color='#c9b26a'}:{spec:PartSpec;color?:string}){
 return <>{spec.footprint.map(([dx,dz],i)=><mesh key={i} position={[dx*PITCH,1.5,dz*PITCH]}>
  <boxGeometry args={[.64,3,.64]}/><meshStandardMaterial color={color} metalness={.8} roughness={.3}/></mesh>)}</>;
}

function centre(spec:PartSpec):[number,number]{
 if(!spec.footprint.length)return[0,0];
 const xs=spec.footprint.map(f=>f[0]),zs=spec.footprint.map(f=>f[1]);
 return[(Math.min(...xs)+Math.max(...xs))/2*PITCH,(Math.min(...zs)+Math.max(...zs))/2*PITCH];
}

function ModuleBody({spec,part,color,depth=16,children}:{spec:PartSpec;part:PartState;color?:string;depth?:number;children?:React.ReactNode}){
 const [cx]=centre(spec);
 const width=Math.max(10,(Math.max(...spec.footprint.map(f=>f[0]))-Math.min(...spec.footprint.map(f=>f[0]))+2)*PITCH);
 return <group>
  <Pins spec={spec}/>
  <group position={[cx,0,-depth/2+1.5]}>
   <Pcb w={width} d={depth} color={color??(part.damaged?'#3a2a26':'#1d5fa5')}>{children}</Pcb>
  </group>
 </group>;
}

function Led({color,brightness,damaged}:{color:string;brightness:number;damaged:boolean}){
 const c=LED_COLORS[color]??color;
 return <group position={[PITCH/2,0,0]}>
  <mesh position={[0,5,0]} castShadow><cylinderGeometry args={[2.5,2.6,5,24]}/>
   <meshStandardMaterial color={c} transparent opacity={.85} emissive={c} emissiveIntensity={damaged?0:brightness*2.5} roughness={.2}/></mesh>
  <mesh position={[0,7.5,0]}><sphereGeometry args={[2.5,24,12,0,Math.PI*2,0,Math.PI/2]}/>
   <meshStandardMaterial color={c} transparent opacity={.85} emissive={c} emissiveIntensity={damaged?0:brightness*2.5}/></mesh>
  {brightness>.05&&!damaged&&<pointLight color={c} intensity={brightness*40} distance={40} position={[0,9,0]}/>}
  {[-PITCH/2,PITCH/2].map((x,i)=><mesh key={i} position={[x,1.5,0]}><cylinderGeometry args={[.25,.25,3]}/><meshStandardMaterial color="#bbb" metalness={.8}/></mesh>)}
 </group>;
}

function Spinner({speed}:{speed:number}){
 const ref=useRef<THREE.Mesh>(null);const invalidate=useThree(s=>s.invalidate);
 useFrame((_,dt)=>{if(ref.current&&speed){ref.current.rotation.y+=dt*speed*20;invalidate();}});
 return <mesh ref={ref} position={[0,22,0]}><boxGeometry args={[14,1.2,2]}/><meshStandardMaterial color="#e2e2e2"/></mesh>;
}

function TextPanel({lines,w,h,on,bg='#9fc33f',fg='#1f2e10',visible=true}:{lines:string[];w:number;h:number;on:boolean;bg?:string;fg?:string;visible?:boolean}){
 const texture=useCanvasTexture(512,128,ctx=>{
  ctx.fillStyle=on?bg:'#3b4f22';ctx.fillRect(0,0,512,128);
  if(on&&visible){ctx.fillStyle=fg;ctx.font='bold 46px monospace';lines.forEach((l,i)=>ctx.fillText(l.padEnd(16).slice(0,16),18,52+i*56));}
 },[lines.join('\n'),on,visible]);
 return <mesh rotation={[-Math.PI/2,0,0]} position={[0,1,0]}><planeGeometry args={[w,h]}/><meshBasicMaterial map={texture}/></mesh>;
}

function Oled({fb,on}:{fb:string;on:boolean}){
 const texture=useCanvasTexture(128,64,ctx=>{
  const image=ctx.createImageData(128,64);
  for(let page=0;page<8;page++)for(let col=0;col<128;col++){
   const byte=on&&fb?parseInt(fb.substr((page*128+col)*2,2),16):0;
   for(let bit=0;bit<8;bit++){const lit=byte>>bit&1,i=((page*8+bit)*128+col)*4;
    image.data[i]=lit?140:6;image.data[i+1]=lit?220:10;image.data[i+2]=lit?255:16;image.data[i+3]=255;}
  }
  ctx.putImageData(image,0,0);
 },[fb,on]);
 texture.magFilter=THREE.NearestFilter;
 return <mesh rotation={[-Math.PI/2,0,0]} position={[0,1.2,0]}><planeGeometry args={[22,11]}/><meshBasicMaterial map={texture}/></mesh>;
}

function Matrix({rows}:{rows:number[]}){
 const texture=useCanvasTexture(128,128,ctx=>{
  ctx.fillStyle='#111';ctx.fillRect(0,0,128,128);
  rows.forEach((row,r)=>{for(let c=0;c<8;c++){ctx.fillStyle=row>>(7-c)&1?'#ff3020':'#331010';ctx.beginPath();ctx.arc(8+c*16,8+r*16,6,0,7);ctx.fill();}});
 },[rows.join(',')]);
 return <mesh rotation={[-Math.PI/2,0,0]} position={[0,3.5,0]}><planeGeometry args={[32,32]}/><meshBasicMaterial map={texture}/></mesh>;
}

function SevenSeg({segments,color}:{segments:Record<string,number>;color:string}){
 const c=LED_COLORS[color]??'#ff3020';
 const bars:[string,number,number,number,number][]=[['a',0,-6,6,1.4],['b',3.2,-3,1.4,6],['c',3.2,3,1.4,6],['d',0,6,6,1.4],['e',-3.2,3,1.4,6],['f',-3.2,-3,1.4,6],['g',0,0,6,1.4]];
 return <group position={[2*PITCH,4,3*PITCH]}>
  <mesh><boxGeometry args={[12.5,7,19]}/><meshStandardMaterial color="#1a1a1a"/></mesh>
  {bars.map(([s,x,z,w,d])=><mesh key={s} position={[x,3.6,z]}><boxGeometry args={[w,.3,d]}/>
   <meshStandardMaterial color={segments[s]>.05?c:'#3a1c1c'} emissive={c} emissiveIntensity={(segments[s]??0)*2}/></mesh>)}
  <mesh position={[5,3.6,7.5]}><sphereGeometry args={[.8]}/><meshStandardMaterial color={segments.dp>.05?c:'#3a1c1c'} emissive={c} emissiveIntensity={(segments.dp??0)*2}/></mesh>
 </group>;
}

export function PartBody({spec,part}:{spec:PartSpec;part:PartState}){
 const s=part.state??{},damaged=!!part.damaged;
 switch(spec.shape){
  case 'axial':case 'axial-diode':{
   const span=(spec.footprint[1]?.[0]??4)*PITCH;
   const bands=spec.shape==='axial'?resistorBands(Number(part.props.ohms??220)):[];
   return <group>
    <mesh position={[span/2,3,0]} rotation={[0,0,Math.PI/2]} castShadow><cylinderGeometry args={[1.2,1.2,span-3,16]}/>
     <meshStandardMaterial color={spec.shape==='axial'?(damaged?'#3b2a1a':'#d8c49a'):'#1a1a1a'}/></mesh>
    {bands.map((b,i)=><mesh key={i} position={[span/2-2.6+i*1.5+(i===3?.6:0),3,0]} rotation={[0,0,Math.PI/2]}><cylinderGeometry args={[1.25,1.25,.5,16]}/><meshStandardMaterial color={b}/></mesh>)}
    {spec.shape==='axial-diode'&&<mesh position={[span-3.2,3,0]} rotation={[0,0,Math.PI/2]}><cylinderGeometry args={[1.25,1.25,.6,16]}/><meshStandardMaterial color="#ddd"/></mesh>}
    {[0,span].map((x,i)=><mesh key={i} position={[x,1.5,0]}><cylinderGeometry args={[.25,.25,3]}/><meshStandardMaterial color="#bbb" metalness={.8}/></mesh>)}
    <mesh position={[span/2,3,0]} rotation={[0,0,Math.PI/2]}><cylinderGeometry args={[.2,.2,span]}/><meshStandardMaterial color="#bbb"/></mesh>
   </group>;
  }
  case 'led':return <Led color={String(part.props.color??'red')} brightness={Number(s.brightness??0)} damaged={damaged}/>;
  case 'led-rgb':{
   const r=Math.round(255*Math.min(1,s.R??0)),g=Math.round(255*Math.min(1,s.G??0)),b=Math.round(255*Math.min(1,s.B??0));
   const color=r+g+b>8?`rgb(${r},${g},${b})`:'#f0f0f0';
   return <group position={[1.5*PITCH,0,0]}><Led color={color} brightness={(r+g+b)/765} damaged={damaged}/></group>;
  }
  case 'capacitor':return <group position={[PITCH/2,0,0]}><mesh position={[0,5,0]} castShadow><cylinderGeometry args={[2.5,2.5,8,20]}/><meshStandardMaterial color={damaged?'#222':'#2a3f8f'}/></mesh>
   <mesh position={[-2.2,5,0]}><boxGeometry args={[.4,8,1.6]}/><meshStandardMaterial color="#ccc"/></mesh></group>;
  case 'pot':{
   const angle=(Number(part.stimuli.position??.5)-.5)*Math.PI*1.5;
   return <group position={[PITCH,0,-3]}><mesh position={[0,4,0]} castShadow><boxGeometry args={[9.5,5,9.5]}/><meshStandardMaterial color="#1f5fa8"/></mesh>
    <mesh position={[0,8,0]} rotation={[0,angle,0]}><cylinderGeometry args={[3,3,4,24]}/><meshStandardMaterial color="#ddd" metalness={.4}/></mesh>
    <mesh position={[0,10.1,1.6]} rotation={[0,angle,0]}><boxGeometry args={[.6,.4,2.4]}/><meshStandardMaterial color="#333"/></mesh><Pins spec={{...spec,footprint:spec.footprint.map(([x,z])=>[x-1,z+3/PITCH]) as [number,number][]}}/></group>;
  }
  case 'button':{
   const pressed=!!part.stimuli.pressed;
   return <group position={[1.5*PITCH,0,PITCH]}><mesh position={[0,2.2,0]} castShadow><boxGeometry args={[6,3.4,6]}/><meshStandardMaterial color="#202020"/></mesh>
    <mesh position={[0,pressed?4:4.8,0]}><cylinderGeometry args={[1.8,1.8,2.2,20]}/><meshStandardMaterial color={pressed?'#c33':'#e04a3a'}/></mesh></group>;
  }
  case 'switch':return <group position={[PITCH,0,0]}><mesh position={[0,3,0]} castShadow><boxGeometry args={[8.6,4,3.6]}/><meshStandardMaterial color="#1b1b1b"/></mesh>
   <mesh position={[part.stimuli.position?1.6:-1.6,5.8,0]}><boxGeometry args={[2,2.6,1.6]}/><meshStandardMaterial color="#d6d6d6"/></mesh></group>;
  case 'to92':return <group position={[PITCH,0,0]}><mesh position={[0,5,0]} castShadow><cylinderGeometry args={[2.4,2.4,5,20,1,false,0,Math.PI]}/><meshStandardMaterial color={damaged?'#3b2a1a':'#161616'}/></mesh></group>;
  case 'to220':return <group position={[PITCH,0,0]}><mesh position={[0,7,0]} castShadow><boxGeometry args={[10,9,4.4]}/><meshStandardMaterial color="#161616"/></mesh>
   <mesh position={[0,14,-1.6]}><boxGeometry args={[10,6,1.2]}/><meshStandardMaterial color="#c8c8c8" metalness={.8}/></mesh></group>;
  case 'dip8':case 'dip16':{
   const n=spec.shape==='dip8'?4:8;
   return <group position={[(n-1)*PITCH/2,0,-1.5*PITCH]}><mesh position={[0,3.5,0]} castShadow><boxGeometry args={[n*PITCH,3.2,6.4]}/><meshStandardMaterial color="#141414"/></mesh>
    <mesh position={[-n*PITCH/2+1.4,5.15,0]}><cylinderGeometry args={[.7,.7,.1,12]}/><meshStandardMaterial color="#333"/></mesh></group>;
  }
  case 'buzzer':return <group position={[1.5*PITCH,0,0]}><mesh position={[0,6,0]} castShadow><cylinderGeometry args={[6,6,8,28]}/><meshStandardMaterial color="#141414" emissive="#ff6020" emissiveIntensity={s.sounding?.25:0}/></mesh></group>;
  case 'ldr':case 'thermistor':return <group position={[PITCH/2,0,0]}><mesh position={[0,6,0]} castShadow><cylinderGeometry args={[2.5,2.5,1.4,20]}/><meshStandardMaterial color={spec.shape==='ldr'?'#c4892b':'#1d1d1d'}/></mesh></group>;
  case 'seven-segment':return <SevenSeg segments={s.segments??{}} color={String(part.props.color??'red')}/>;
  case 'servo':{
   const angle=(Number(s.angle??90)-90)*Math.PI/180;
   return <group position={[PITCH,0,-14]}><mesh position={[0,11,0]} castShadow><boxGeometry args={[23,22,12.5]}/><meshStandardMaterial color="#2e5bd6"/></mesh>
    <mesh position={[-5,23,0]}><cylinderGeometry args={[2.4,2.4,2.4,16]}/><meshStandardMaterial color="#fafafa"/></mesh>
    <group position={[-5,24.6,0]} rotation={[0,angle,0]}><mesh position={[0,0,6]}><boxGeometry args={[3.2,1.4,15]}/><meshStandardMaterial color="#fafafa"/></mesh></group><Pins spec={{...spec,footprint:spec.footprint.map(([x,z])=>[x-1,z+14/PITCH]) as [number,number][]}}/></group>;
  }
  case 'motor':return <group position={[PITCH,0,-14]}><mesh position={[0,10,0]} rotation={[Math.PI/2,0,0]} castShadow><cylinderGeometry args={[10,10,25,28]}/><meshStandardMaterial color="#c9c9c9" metalness={.7} roughness={.35}/></mesh><Spinner speed={Number(s.speed??0)}/></group>;
  case 'stepper':{
   const angle=Number(s.angle??0)*Math.PI/180;
   return <group position={[2.5*PITCH,0,-24]}><mesh position={[0,9,0]} castShadow><cylinderGeometry args={[14,14,18,32]}/><meshStandardMaterial color="#c8c8c8" metalness={.6}/></mesh>
    <group position={[0,19,0]} rotation={[0,-angle,0]}><mesh position={[0,0,4]}><boxGeometry args={[2,2,10]}/><meshStandardMaterial color="#e2c23a"/></mesh></group></group>;
  }
  case 'relay':return <ModuleBody spec={spec} part={part} depth={26}><mesh position={[0,8,-2]}><boxGeometry args={[15,15,19]}/><meshStandardMaterial color="#1f4fd0"/></mesh>
   <mesh position={[6,1.4,9]}><sphereGeometry args={[1]}/><meshStandardMaterial color="#f33" emissive="#f33" emissiveIntensity={s.energized?3:0}/></mesh></ModuleBody>;
  case 'oled':return <ModuleBody spec={spec} part={part} depth={27} color="#13213d"><Oled fb={String(s.fb??'')} on={!!s.on}/></ModuleBody>;
  case 'lcd1602':return <ModuleBody spec={spec} part={part} depth={36} color="#1b6b2a">
   <mesh position={[0,1.5,0]}><boxGeometry args={[71,3,24]}/><meshStandardMaterial color="#111"/></mesh>
   <group position={[0,1.7,0]}><TextPanel lines={s.lines??['','']} w={64} h={16} on={s.backlight!==false} visible={s.visible!==false}/></group></ModuleBody>;
  case 'matrix':return <ModuleBody spec={spec} part={part} depth={34} color="#1b5a2a"><Matrix rows={s.rows??[0,0,0,0,0,0,0,0]}/></ModuleBody>;
  case 'strip':{
   const colors:string[]=s.colors??[];
   return <group>{colors.map((c,i)=><mesh key={i} position={[i*10,3,-8]}><boxGeometry args={[5,1.6,5]}/>
    <meshStandardMaterial color={c==='#000000'?'#f4f4f4':c} emissive={c} emissiveIntensity={c==='#000000'?0:2}/></mesh>)}
    <mesh position={[(colors.length-1)*5,2,-8]}><boxGeometry args={[colors.length*10,.6,10]}/><meshStandardMaterial color="#111"/></mesh><Pins spec={spec}/></group>;
  }
  case 'battery':return <group position={[PITCH/2,0,-16]}><mesh position={[0,9,0]} castShadow><boxGeometry args={[26,17,46]}/><meshStandardMaterial color="#2a2a2a"/></mesh>
   <mesh position={[0,17.6,10]}><boxGeometry args={[24,.4,20]}/><meshStandardMaterial color="#e6b422"/></mesh></group>;
  case 'module-sonar':return <ModuleBody spec={spec} part={part} depth={20}>
   {[-13,13].map(x=><mesh key={x} position={[x,7,0]} rotation={[0,0,0]}><cylinderGeometry args={[8,8,12,28]}/><meshStandardMaterial color="#c7c7c7" metalness={.7}/></mesh>)}</ModuleBody>;
  case 'module-pir':return <ModuleBody spec={spec} part={part} depth={24} color="#1d6b32"><mesh position={[0,1,0]}><sphereGeometry args={[11,24,12,0,Math.PI*2,0,Math.PI/2]}/><meshStandardMaterial color="#f2f2f2" transparent opacity={.92}/></mesh></ModuleBody>;
  case 'module-dht':return <ModuleBody spec={spec} part={part} depth={20}><mesh position={[0,4,0]}><boxGeometry args={[15,7,12]}/><meshStandardMaterial color="#3f8fd6"/></mesh></ModuleBody>;
  case 'module-gas':return <ModuleBody spec={spec} part={part} depth={22}><mesh position={[0,5,0]}><cylinderGeometry args={[9,9,9,24]}/><meshStandardMaterial color="#9a9a9a" metalness={.5} wireframe/></mesh></ModuleBody>;
  case 'keypad':return <group position={[3.5*PITCH,0,-40]}><mesh position={[0,1,0]}><boxGeometry args={[69,.8,76]}/><meshStandardMaterial color="#1b1b1b"/></mesh>
   {Array.from({length:16},(_,k)=><mesh key={k} position={[-24+(k%4)*16,1.6,-27+Math.floor(k/4)*17]}><boxGeometry args={[12,.8,12]}/>
    <meshStandardMaterial color={part.stimuli.key===k?'#e04a3a':k%4===3?'#d33':'#3b6bd6'}/></mesh>)}</group>;
  case 'breadboard':return null;
  default:return <ModuleBody spec={spec} part={part}/>;
 }
}

export function partWorldRotation(rot:number){return -((rot%4)+4)%4*Math.PI/2;}
export {rotate};
