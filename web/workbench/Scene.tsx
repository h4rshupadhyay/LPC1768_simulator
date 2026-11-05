// The 3D bench: target board, breadboards, parts, jumper wires and ribbon cables.
import {memo,useEffect,useLayoutEffect,useMemo,useRef,useState} from 'react';
import {Canvas,useThree,type ThreeEvent} from '@react-three/fiber';
import {OrbitControls,OrthographicCamera,PerspectiveCamera,Html} from '@react-three/drei';
import * as THREE from 'three';
import {renderToStaticMarkup} from 'react-dom/server';
import {BoardArtwork} from '../BoardArtwork';
import type {Layout} from '../types';
import type {ViewState} from '../viewState';
import type {PartSpec,PartState,Placement,Target} from './types';
import {PartBody,partWorldRotation,useCanvasTexture} from './Parts3D';
import {ALS_ORIGIN,ALS_SCALE,ALS_POWER_TAP,BB_COLUMNS,BOARD_TOP,BREADBOARD_TOP,PITCH,alsHeaderPins,alsPoint,
 barePins,breadboardBox,breadboardHoles,mbedPins,MBED_ORIGIN,BARE_ORIGIN,partPins,targetEndpoints} from './geometry';

// Set while a part is being placed: other objects then let pointer events through.
const PLACING={current:false};

export type View='iso'|'top'|'front'|'board'|'focus';
export interface Pick {endpoint:string;x:number;y:number;z:number}

interface Props {
 target:Target;layout:Layout;state:ViewState;specs:Record<string,PartSpec>;parts:PartState[];
 wires:[string,string,string][];view:View;selected:string|null;highlight:Set<string>;
 pendingWire:string|null;ghost:{spec:PartSpec;placement:Placement}|null;
 onPin:(pick:Pick)=>void;onHover:(endpoint:string|null)=>void;onSelect:(id:string|null)=>void;
 onBench:(x:number,z:number,clicked:boolean)=>void;onWire:(a:string,b:string)=>void;
 onKit:(action:unknown)=>void;onReset:()=>void;hoverInfo:string|null;
}

function surfaceY(parts:PartState[],x:number,z:number){
 for(const p of parts){
  if(p.type!=='breadboard')continue;
  const box=breadboardBox(String(p.props.size??'full'));
  const bx=p.placement.x??0,bz=p.placement.z??0;
  if(x>=bx+box.x0&&x<=bx+box.x1&&z>=bz+box.z0&&z<=bz+box.z1)return BREADBOARD_TOP;
 }
 return 0;
}

export function endpointPositions(target:Target,layout:Layout,parts:PartState[],specs:Record<string,PartSpec>){
 const map=new Map<string,[number,number,number]>();
 for(const e of targetEndpoints(target,layout,Object.keys(layout.headers)))map.set(e.endpoint,[e.x,e.y,e.z]);
 for(const p of parts){
  if(p.type==='breadboard'){
   const bx=p.placement.x??0,bz=p.placement.z??0;
   for(const h of breadboardHoles(String(p.props.size??'full')))map.set(`${p.id}.${h.name}`,[bx+h.x,BREADBOARD_TOP,bz+h.z]);
   continue;
  }
  const spec=specs[p.type];if(!spec)continue;
  const y=surfaceY(parts,p.placement.x??0,p.placement.z??0);
  for(const [pin,[x,z]] of Object.entries(partPins(spec,p.placement)))map.set(`${p.id}.${pin}`,[x,y+4,z]);
 }
 return map;
}

// -- target boards ---------------------------------------------------------------------
function useBoardTexture(){
 const [texture,setTexture]=useState<THREE.Texture|null>(null);
 useEffect(()=>{
  const markup=renderToStaticMarkup(<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1440 1040" width="2880" height="2080"><BoardArtwork/></svg>);
  const url=URL.createObjectURL(new Blob([markup],{type:'image/svg+xml'}));
  const image=new Image();
  image.onload=()=>{
   const canvas=document.createElement('canvas');canvas.width=2880;canvas.height=2080;
   canvas.getContext('2d')!.drawImage(image,0,0,2880,2080);
   const t=new THREE.CanvasTexture(canvas);t.colorSpace=THREE.SRGBColorSpace;t.anisotropy=8;setTexture(t);
   URL.revokeObjectURL(url);
  };
  image.src=url;
  return()=>URL.revokeObjectURL(url);
 },[]);
 return texture;
}

function Header({pins,onPin,onHover,label,pendingWire}:{pins:{endpoint:string;x:number;z:number}[];onPin:Props['onPin'];onHover:Props['onHover'];label?:string;pendingWire:string|null}){
 return <group>{pins.map(p=><PinTarget key={p.endpoint} {...p} y={BOARD_TOP} height={6} onPin={onPin} onHover={onHover} active={pendingWire===p.endpoint}/>)}
  {label&&pins[0]&&<Html position={[pins[0].x,BOARD_TOP+9,pins[0].z]} center className="bench-label">{label}</Html>}
 </group>;
}

function PinTarget({endpoint,x,z,y,height,onPin,onHover,active,color='#d8c46e'}:{endpoint:string;x:number;z:number;y:number;height:number;onPin:Props['onPin'];onHover:Props['onHover'];active:boolean;color?:string}){
 const [hover,setHover]=useState(false);
 return <mesh position={[x,y+height/2,z]}
  onPointerOver={e=>{if(PLACING.current)return;e.stopPropagation();setHover(true);onHover(endpoint);}}
  onPointerOut={()=>{setHover(false);onHover(null);}}
  onClick={e=>{if(PLACING.current)return;e.stopPropagation();onPin({endpoint,x,y:y+height,z});}}>
  <boxGeometry args={[.9,height,.9]}/>
  <meshStandardMaterial color={active?'#5ff':hover?'#fff3a0':color} emissive={active||hover?'#3aa':'#000'} metalness={.7} roughness={.3}/>
 </mesh>;
}

function AlsBoard({layout,state,onPin,onHover,onKit,onReset,pendingWire}:{layout:Layout;state:ViewState}&Pick2){
 const texture=useBoardTexture();
 const w=layout.width*ALS_SCALE,d=layout.height*ALS_SCALE;
 const lcd=layout.lcd,seven=layout.seven;
 const [lx,lz]=alsPoint(lcd[0]+lcd[2]/2,lcd[1]+lcd[3]/2);
 const [sx,sz]=alsPoint(seven[0]+seven[2]/2,seven[1]+seven[3]/2);
 const lcdTexture=useCanvasTexture(512,128,ctx=>{
  const on=state.jumpers.JP16==='closed';
  ctx.fillStyle=on?'#bdd54e':'#426523';ctx.fillRect(0,0,512,128);
  if(on){ctx.fillStyle='#233712';ctx.font='bold 44px monospace';state.lcd.forEach((l,i)=>ctx.fillText(l,16,52+i*54));}
 },[state.lcd.join('|'),state.jumpers.JP16]);
 const segTexture=useCanvasTexture(400,144,ctx=>{
  ctx.fillStyle='#17201a';ctx.fillRect(0,0,400,144);
  const bars:[number,number,number,number][]=[[16,6,52,12],[66,16,12,52],[66,76,12,52],[16,126,52,12],[6,76,12,52],[6,16,12,52],[16,66,52,12]];
  state.segments.forEach((pattern,d)=>{const ox=(3-d)*100+12;
   bars.forEach(([x,y,w2,h],i)=>{ctx.fillStyle=pattern&(1<<i)?'#ff4b36':'#3a2a26';ctx.fillRect(ox+x,y,w2,h);});
   ctx.fillStyle=pattern&128?'#ff4b36':'#3a2a26';ctx.beginPath();ctx.arc(ox+86,130,6,0,7);ctx.fill();});
 },[state.segments.join(',')]);
 const headers=Object.keys(layout.headers);
 const cableSet=new Set(state.cables.flat());
 return <group>
  <mesh position={[ALS_ORIGIN[0]+w/2,BOARD_TOP/2,ALS_ORIGIN[1]+d/2]} receiveShadow castShadow>
   <boxGeometry args={[w,BOARD_TOP,d]}/>
   <meshStandardMaterial attach="material-0" color="#064d40"/><meshStandardMaterial attach="material-1" color="#064d40"/>
   <meshStandardMaterial attach="material-2" map={texture??undefined} color={texture?'#fff':'#075846'} roughness={.8}/>
   <meshStandardMaterial attach="material-3" color="#064d40"/><meshStandardMaterial attach="material-4" color="#064d40"/>
   <meshStandardMaterial attach="material-5" color="#064d40"/>
  </mesh>
  <mesh position={[lx,BOARD_TOP+1.2,lz]} rotation={[-Math.PI/2,0,0]}><planeGeometry args={[lcd[2]*ALS_SCALE,lcd[3]*ALS_SCALE]}/><meshBasicMaterial map={lcdTexture}/></mesh>
  <mesh position={[sx,BOARD_TOP+1.2,sz]} rotation={[-Math.PI/2,0,0]}><planeGeometry args={[seven[2]*ALS_SCALE,seven[3]*ALS_SCALE]}/><meshBasicMaterial map={segTexture}/></mesh>
  {layout.leds.map(([px,py],i)=>{const [x,z]=alsPoint(px,py);return <mesh key={i} position={[x,BOARD_TOP+1.4,z]}>
   <sphereGeometry args={[1.6,16,8,0,Math.PI*2,0,Math.PI/2]}/><meshStandardMaterial color={state.leds[i]?'#ffca62':'#6b5a3a'} emissive="#ff8132" emissiveIntensity={state.leds[i]?2.5:0}/></mesh>;})}
  {(()=>{const [x,z]=alsPoint(...layout.ld10);return <mesh position={[x,BOARD_TOP+1.4,z]}><sphereGeometry args={[1.4,16,8,0,Math.PI*2,0,Math.PI/2]}/>
   <meshStandardMaterial color="#ff873f" emissive="#ff4a23" emissiveIntensity={state.pwm*3}/></mesh>;})()}
  <KitButton at={layout.sw2} pressed={state.sw2} label="SW2" onPress={p=>onKit({action:'switch',pressed:p})}/>
  <KitButton at={layout.sw1} pressed={false} label="RST" onPress={p=>{if(p)onReset();}}/>
  {Array.from({length:16},(_,k)=><KitButton key={k} at={[layout.keypad.origin[0]+(k%4)*layout.keypad.step[0],layout.keypad.origin[1]+Math.floor(k/4)*layout.keypad.step[1]]}
   pressed={state.keys.includes(k)} label={k.toString(16).toUpperCase()} onPress={p=>onKit({action:'key',key:k,pressed:p})}/>)}
  {Object.entries(layout.jumpers).map(([name,[px,py]])=>{const [x,z]=alsPoint(px,py);const closed=state.jumpers[name]!=='open';
   return <mesh key={name} position={[x,BOARD_TOP+2,z]} onClick={e=>{if(PLACING.current)return;e.stopPropagation();onKit({action:'jumper-cycle',name});}}>
    <boxGeometry args={[5,3,2.6]}/><meshStandardMaterial color={closed?'#1f1f1f':'#9b8a4a'}/>
    <Html position={[0,4,0]} center className="bench-label">{name} {state.jumpers[name]}</Html></mesh>;})}
  {headers.map(h=><group key={h}>
   {(()=>{const [cx,cz]=alsPoint(...layout.headers[h]);const vertical=layout.headerOrientations[h]==='vertical';
    return <mesh position={[cx,BOARD_TOP+1.6,cz]}><boxGeometry args={vertical?[6,3.2,14]:[14,3.2,6]}/>
     <meshStandardMaterial color={cableSet.has(h)?'#1d4f3d':'#111'}/></mesh>;})()}
   <Header pins={alsHeaderPins(layout,h).map(([x,z],i)=>({endpoint:`kit.${h}.${i+1}`,x,z}))} onPin={onPin} onHover={onHover} label={h} pendingWire={pendingWire}/>
  </group>)}
  <Header pins={ALS_POWER_TAP.map(([name,px,py])=>{const [x,z]=alsPoint(px,py);return {endpoint:`kit.${name}`,x,z};})} onPin={onPin} onHover={onHover} label="PWR 3V3·5V·GND" pendingWire={pendingWire}/>
  {state.cables.map(([a,b])=><Ribbon key={a+b} a={layout.headers[a]} b={layout.headers[b]}/>)}
 </group>;
}
type Pick2={onPin:Props['onPin'];onHover:Props['onHover'];onKit:Props['onKit'];onReset:Props['onReset'];pendingWire:string|null};

function KitButton({at,pressed,label,onPress}:{at:[number,number];pressed:boolean;label:string;onPress:(p:boolean)=>void}){
 const [x,z]=alsPoint(at[0],at[1]);
 return <mesh position={[x,BOARD_TOP+(pressed?1.4:2.2),z]}
  onPointerDown={e=>{if(PLACING.current)return;e.stopPropagation();(e.target as Element)?.setPointerCapture?.(e.pointerId);onPress(true);}}
  onPointerUp={e=>{e.stopPropagation();onPress(false);}} onPointerLeave={()=>{if(pressed)onPress(false);}}>
  <cylinderGeometry args={[2.2,2.2,2,20]}/><meshStandardMaterial color={pressed?'#625c3a':'#15221c'}/>
  <Html position={[0,2.2,0]} center className="bench-key" pointerEvents="none">{label}</Html>
 </mesh>;
}

function Ribbon({a,b}:{a:[number,number];b:[number,number]}){
 const curve=useMemo(()=>{
  const [ax,az]=alsPoint(...a),[bx,bz]=alsPoint(...b);
  const lift=Math.max(25,Math.hypot(bx-ax,bz-az)*.35);
  return new THREE.CubicBezierCurve3(new THREE.Vector3(ax,BOARD_TOP+5,az),new THREE.Vector3(ax,BOARD_TOP+lift,az),
   new THREE.Vector3(bx,BOARD_TOP+lift,bz),new THREE.Vector3(bx,BOARD_TOP+5,bz));
 },[a,b]);
 const geometry=useMemo(()=>new THREE.TubeGeometry(curve,48,2.2,6,false),[curve]);
 return <mesh geometry={geometry} castShadow><meshStandardMaterial color="#cfd3d3" roughness={.6}/></mesh>;
}

function MbedBoard({state,onPin,onHover,pendingWire}:{state:ViewState}&Omit<Pick2,'onKit'|'onReset'>){
 const pins=mbedPins();
 const leds=(state as any).mbedLeds as boolean[]|undefined;
 return <group>
  <mesh position={[MBED_ORIGIN[0],BOARD_TOP/2+6,MBED_ORIGIN[1]]} castShadow><boxGeometry args={[54,1.6,26]}/><meshStandardMaterial color="#1b4aa5"/></mesh>
  <mesh position={[MBED_ORIGIN[0]-20,9,MBED_ORIGIN[1]]}><boxGeometry args={[8,3,8]}/><meshStandardMaterial color="#bbb" metalness={.7}/></mesh>
  <mesh position={[MBED_ORIGIN[0]+2,8,MBED_ORIGIN[1]]}><boxGeometry args={[14,1.4,14]}/><meshStandardMaterial color="#121212"/></mesh>
  <Html position={[MBED_ORIGIN[0]+2,11,MBED_ORIGIN[1]]} center className="bench-label">mbed LPC1768</Html>
  {[0,1,2,3].map(i=><mesh key={i} position={[MBED_ORIGIN[0]+16+i*3,8,MBED_ORIGIN[1]+6]}><boxGeometry args={[1.6,.8,1]}/>
   <meshStandardMaterial color="#3d7bff" emissive="#3d7bff" emissiveIntensity={leds?.[i]?3:0}/></mesh>)}
  {pins.map(p=><PinTarget key={p.name} endpoint={`mbed.${p.name}`} x={p.x} z={p.z} y={BOARD_TOP+5} height={4}
   onPin={onPin} onHover={onHover} active={pendingWire===`mbed.${p.name}`} color={/^p\d/.test(p.name)||['GND','VOUT','VU'].includes(p.name)?'#d8c46e':'#777'}/>)}
 </group>;
}

function BareBoard({onPin,onHover,pendingWire}:Omit<Pick2,'onKit'|'onReset'>){
 const pins=barePins();
 return <group>
  <mesh position={[BARE_ORIGIN[0],BOARD_TOP/2,BARE_ORIGIN[1]]} castShadow receiveShadow><boxGeometry args={[110,BOARD_TOP,48]}/><meshStandardMaterial color="#0f5a3a"/></mesh>
  <mesh position={[BARE_ORIGIN[0],BOARD_TOP+.8,BARE_ORIGIN[1]]} rotation={[0,Math.PI/4,0]}><boxGeometry args={[14,1.4,14]}/><meshStandardMaterial color="#141414"/></mesh>
  <Html position={[BARE_ORIGIN[0],BOARD_TOP+4,BARE_ORIGIN[1]+11]} center className="bench-label">LPC1768 LQFP100 breakout</Html>
  {pins.map((p,i)=><PinTarget key={i} endpoint={`mcu.${p.name}`} x={p.x} z={p.z} y={BOARD_TOP} height={6} onPin={onPin} onHover={onHover}
   active={pendingWire===`mcu.${p.name}`} color={p.name==='GND'?'#555':p.name==='3V3'?'#d55':'#d8c46e'}/>)}
 </group>;
}

// -- breadboards --------------------------------------------------------------------------
const Breadboard3D=memo(function Breadboard3D({part,onPin,onHover,selected,onSelect}:{part:PartState;onPin:Props['onPin'];onHover:Props['onHover'];selected:boolean;onSelect:Props['onSelect']}){
 const size=String(part.props.size??'full'),box=breadboardBox(size);
 const holes=useMemo(()=>breadboardHoles(size),[size]);
 const ref=useRef<THREE.InstancedMesh>(null);
 const bx=part.placement.x??0,bz=part.placement.z??0;
 useLayoutEffect(()=>{
  const m=new THREE.Matrix4();
  holes.forEach((h,i)=>{m.setPosition(h.x,BREADBOARD_TOP+.02,h.z);ref.current!.setMatrixAt(i,m);});
  ref.current!.instanceMatrix.needsUpdate=true;
 },[holes]);
 const hole=(e:ThreeEvent<PointerEvent|MouseEvent>)=>e.instanceId!==undefined?holes[e.instanceId]:null;
 return <group position={[bx,0,bz]}>
  <mesh position={[(box.x0+box.x1)/2,BREADBOARD_TOP/2,(box.z0+box.z1)/2]} castShadow receiveShadow onClick={e=>{if(PLACING.current)return;e.stopPropagation();onSelect(part.id);}}>
   <boxGeometry args={[box.x1-box.x0,BREADBOARD_TOP,box.z1-box.z0]}/><meshStandardMaterial color={selected?'#fff6e0':'#f1efe8'} roughness={.9}/>
  </mesh>
  <mesh position={[(box.x0+box.x1)/2,BREADBOARD_TOP+.01,3.81]}><boxGeometry args={[box.x1-box.x0,.05,2.2]}/><meshStandardMaterial color="#cfccc2"/></mesh>
  {/* Rail stripes: red beside the + rows (tp, bp), blue beside the − rows (tn, bn). */}
  {size!=='mini'&&([[-17.78-1.6,'#d33'],[-15.24+1.6,'#2155c9'],[22.86-1.6,'#d33'],[25.4+1.6,'#2155c9']] as [number,string][]).map(([z,c])=>
   <mesh key={z} position={[(box.x0+box.x1)/2,BREADBOARD_TOP+.02,z]}>
    <boxGeometry args={[box.x1-box.x0-4,.04,.3]}/><meshBasicMaterial color={c}/></mesh>)}
  <instancedMesh ref={ref} args={[undefined,undefined,holes.length]}
   onPointerMove={e=>{if(PLACING.current)return;const h=hole(e);if(h){e.stopPropagation();onHover(`${part.id}.${h.name}`);}}}
   onPointerOut={()=>onHover(null)}
   onClick={e=>{if(PLACING.current)return;const h=hole(e);if(h){e.stopPropagation();onPin({endpoint:`${part.id}.${h.name}`,x:bx+h.x,y:BREADBOARD_TOP,z:bz+h.z});}}}>
   <boxGeometry args={[1.1,.06,1.1]}/><meshBasicMaterial color="#2a2a2a"/>
  </instancedMesh>
  <Html position={[box.x0+4,BREADBOARD_TOP+.5,box.z1-2]} className="bench-label">{part.id}</Html>
 </group>;
});

// -- parts and wires ------------------------------------------------------------------------
function PartMesh({part,spec,parts,selected,highlighted,onSelect,onPin,onHover,pendingWire}:{part:PartState;spec:PartSpec;parts:PartState[];selected:boolean;highlighted:boolean;
 onSelect:Props['onSelect'];onPin:Props['onPin'];onHover:Props['onHover'];pendingWire:string|null}){
 const x=part.placement.x??0,z=part.placement.z??0,rot=part.placement.rot??0;
 const y=surfaceY(parts,x,z);
 const pins=partPins(spec,part.placement);
 return <group>
  <group position={[x,y,z]} rotation={[0,partWorldRotation(rot),0]} onClick={e=>{if(PLACING.current)return;e.stopPropagation();onSelect(part.id);}}>
   <PartBody spec={spec} part={part}/>
   {(selected||highlighted||part.damaged)&&<mesh position={[0,.3,0]} rotation={[-Math.PI/2,0,0]}>
    <ringGeometry args={[6,7.2,32]}/><meshBasicMaterial color={part.damaged?'#ff4444':highlighted?'#ffb02e':'#5ff'}/></mesh>}
   {part.damaged&&<Html position={[0,16,0]} center className="bench-damage">⚠ damaged</Html>}
  </group>
  {Object.entries(pins).map(([pin,[px,pz]])=><PinTarget key={pin} endpoint={`${part.id}.${pin}`} x={px} z={pz} y={y+3.2} height={1.6}
   onPin={onPin} onHover={onHover} active={pendingWire===`${part.id}.${pin}`} color="#e0c060"/>)}
 </group>;
}

function Wire({a,b,color,onClick}:{a:[number,number,number];b:[number,number,number];color:string;onClick:()=>void}){
 const geometry=useMemo(()=>{
  const start=new THREE.Vector3(...a),end=new THREE.Vector3(...b);
  const lift=Math.min(60,6+start.distanceTo(end)*.25);
  const curve=new THREE.CubicBezierCurve3(start,start.clone().add(new THREE.Vector3(0,lift,0)),end.clone().add(new THREE.Vector3(0,lift,0)),end);
  return new THREE.TubeGeometry(curve,32,.55,6,false);
 },[a[0],a[1],a[2],b[0],b[1],b[2]]);
 return <mesh geometry={geometry} castShadow onClick={e=>{e.stopPropagation();onClick();}}><meshStandardMaterial color={color} roughness={.45}/></mesh>;
}

function Ghost({spec,placement,parts}:{spec:PartSpec;placement:Placement;parts:PartState[]}){
 const y=spec.kind==='breadboard'?0:surfaceY(parts,placement.x,placement.z);
 if(spec.kind==='breadboard'){
  const box=breadboardBox(String(spec.defaults.size??'full'));
  return <mesh position={[placement.x+(box.x0+box.x1)/2,BREADBOARD_TOP/2,placement.z+(box.z0+box.z1)/2]}>
   <boxGeometry args={[box.x1-box.x0,BREADBOARD_TOP,box.z1-box.z0]}/><meshStandardMaterial color="#5ff" transparent opacity={.25}/></mesh>;
 }
 const ghostPart:PartState={id:'ghost',type:spec.kind,props:{...spec.defaults} as Record<string,unknown>,stimuli:{},placement,mount:{},damaged:null,state:{},pins:{}};
 return <group position={[placement.x,y,placement.z]} rotation={[0,partWorldRotation(placement.rot),0]}>
  <group><PartBody spec={spec} part={ghostPart}/></group>
  <mesh position={[0,.4,0]} rotation={[-Math.PI/2,0,0]}><ringGeometry args={[5,6,24]}/><meshBasicMaterial color="#5ff"/></mesh>
 </group>;
}

function Cameras({view,focus}:{view:View;focus:[number,number,number]|null}){
 const controls=useThree(s=>s.controls) as unknown as {target:THREE.Vector3;update:()=>void}|null;
 const camera=useThree(s=>s.camera);
 useEffect(()=>{
  const positions:Record<View,[number,number,number]>={iso:[40,330,360],top:[-60,600,0.01],front:[-60,90,340],board:[-150,260,120],focus:focus?[focus[0]+60,focus[1]+120,focus[2]+120]:[0,200,200]};
  const targets:Record<View,[number,number,number]>={iso:[-40,0,10],top:[-60,0,0],front:[-60,0,0],board:[-156,0,0],focus:focus??[0,0,0]};
  camera.position.set(...positions[view]);
  if(controls){controls.target.set(...targets[view]);controls.update();}
  else camera.lookAt(...targets[view]);
 },[view,focus?.[0],focus?.[2],controls,camera]);
 return null;
}

export function Scene(props:Props){
 const {target,layout,state,specs,parts,wires,view,selected,highlight,pendingWire,ghost,onPin,onHover,onSelect,onBench,onKit,onReset}=props;
 const positions=useMemo(()=>endpointPositions(target,layout,parts,specs),[target,layout,parts,specs]);
 const selectedPart=parts.find(p=>p.id===selected);
 const focus:[number,number,number]|null=selectedPart?[selectedPart.placement.x??0,0,selectedPart.placement.z??0]:null;
 const top=view==='top';
 PLACING.current=!!ghost;
 return <Canvas frameloop="demand" shadows dpr={[1,2]} className="bench-canvas" gl={{antialias:true,preserveDrawingBuffer:true}}
  onPointerMissed={()=>onSelect(null)}>
  {top?<OrthographicCamera makeDefault position={[-60,600,0.01]} zoom={2.6} near={1} far={3000}/>
   :<PerspectiveCamera makeDefault position={[40,330,360]} fov={38} near={1} far={5000}/>}
  <OrbitControls makeDefault enableRotate={!top} maxPolarAngle={Math.PI/2.05} minDistance={30} maxDistance={1600}/>
  <Cameras view={view} focus={focus}/>
  <color attach="background" args={['#0d131a']}/>
  <hemisphereLight args={['#dfe9ff','#2a2018',.9]}/>
  <directionalLight position={[-120,400,220]} intensity={2.2} castShadow shadow-mapSize={[2048,2048]}
   shadow-camera-left={-420} shadow-camera-right={420} shadow-camera-top={300} shadow-camera-bottom={-300}/>
  <mesh rotation={[-Math.PI/2,0,0]} position={[-40,-.05,0]} receiveShadow
   onPointerMove={e=>onBench(e.point.x,e.point.z,false)} onClick={e=>{if(ghost){e.stopPropagation();onBench(e.point.x,e.point.z,true);}}}>
   <planeGeometry args={[1400,900]}/><meshStandardMaterial color="#3b2f25" roughness={.95}/>
  </mesh>
  <gridHelper args={[1400,140,'#4a3b2e','#43362a']} position={[-40,0,0]}/>
  {target==='als'&&<AlsBoard layout={layout} state={state} onPin={onPin} onHover={onHover} onKit={onKit} onReset={onReset} pendingWire={pendingWire}/>}
  {target==='mbed'&&<MbedBoard state={state} onPin={onPin} onHover={onHover} pendingWire={pendingWire}/>}
  {target==='bare'&&<BareBoard onPin={onPin} onHover={onHover} pendingWire={pendingWire}/>}
  {parts.map(p=>p.type==='breadboard'
   ?<Breadboard3D key={p.id} part={p} onPin={onPin} onHover={onHover} selected={selected===p.id} onSelect={onSelect}/>
   :specs[p.type]?<PartMesh key={p.id} part={p} spec={specs[p.type]} parts={parts} selected={selected===p.id} highlighted={highlight.has(p.id)}
    onSelect={onSelect} onPin={onPin} onHover={onHover} pendingWire={pendingWire}/>:null)}
  {wires.map(([a,b,color])=>{const pa=positions.get(a),pb=positions.get(b);
   return pa&&pb?<Wire key={a+'|'+b} a={pa} b={pb} color={color} onClick={()=>props.onWire(a,b)}/>:null;})}
  {ghost&&<>
   <Ghost spec={ghost.spec} placement={ghost.placement} parts={parts}/>
   {/* While placing, an invisible plane at breadboard height takes every pointer event,
       so clicks over existing parts drop the new part instead of selecting them. */}
   <mesh rotation={[-Math.PI/2,0,0]} position={[-40,BREADBOARD_TOP,0]} renderOrder={999}
    onPointerMove={e=>{e.stopPropagation();onBench(e.point.x,e.point.z,false);}}
    onClick={e=>{e.stopPropagation();onBench(e.point.x,e.point.z,true);}}>
    <planeGeometry args={[1400,900]}/><meshBasicMaterial transparent opacity={0} depthWrite={false} depthTest={false}/>
   </mesh>
  </>}
  {props.hoverInfo&&pendingWire&&positions.get(pendingWire)&&<Html position={positions.get(pendingWire)} center className="bench-pending">wire from {pendingWire}</Html>}
 </Canvas>;
}

export {BB_COLUMNS,PITCH};
