import {useEffect,useState} from 'react';
import {LIMITS,PRESETS,type CameraStore,type CameraView} from './camera';

// On-screen view controls: sliders for rotate, tilt, zoom and pan, plus preset views.
// They follow mouse orbiting too, because both write the same camera store.
export function CameraPanel({store,focus}:{store:CameraStore;focus:[number,number]|null}){
 const [view,setView]=useState<CameraView>(store.get());
 const [open,setOpen]=useState(true);
 useEffect(()=>{
  let frame=0;
  return store.subscribe(next=>{
   cancelAnimationFrame(frame);
   frame=requestAnimationFrame(()=>setView(next));
  });
 },[store]);
 const update=(patch:Partial<CameraView>)=>store.set({...store.get(),...patch},'ui');
 const slider=(label:string,key:keyof CameraView,[min,max]:readonly [number,number],display:(v:number)=>string,invert=false)=>{
  const value=invert?min+max-view[key]:view[key];
  return <label className="camera-row">
   <span>{label}</span>
   <input type="range" aria-label={label} min={min} max={max} step={1} value={Math.round(value)}
    onChange={e=>{const v=Number(e.target.value);update({[key]:invert?min+max-v:v});}}/>
   <output>{display(view[key])}</output>
  </label>;
 };
 const zoomPercent=(distance:number)=>`${Math.round(560/distance*100)}%`;
 return <div className={`camera-panel${open?'':' collapsed'}`} role="group" aria-label="3D view controls">
  <button className="camera-toggle" aria-expanded={open} onClick={()=>setOpen(!open)}>{open?'▾':'▸'} View</button>
  {open&&<>
   <div className="camera-presets">
    {([['bench','Bench'],['kit','Kit'],['top','Top'],['front','Front'],['parts','Parts']] as const).map(([key,label])=>
     <button key={key} onClick={()=>store.set(PRESETS[key],'ui')}>{label}</button>)}
    <button disabled={!focus} onClick={()=>focus&&store.set({...store.get(),x:focus[0],z:focus[1],distance:160,elevation:55},'ui')}>Selected</button>
   </div>
   {slider('Rotate','azimuth',LIMITS.azimuth,v=>`${Math.round(v)}°`)}
   {slider('Tilt','elevation',LIMITS.elevation,v=>`${Math.round(v)}°`)}
   {slider('Zoom','distance',LIMITS.distance,zoomPercent,true)}
   {slider('Pan ←→','x',LIMITS.x,v=>`${Math.round(v)} mm`)}
   {slider('Pan ↑↓','z',LIMITS.z,v=>`${Math.round(v)} mm`)}
  </>}
 </div>;
}
