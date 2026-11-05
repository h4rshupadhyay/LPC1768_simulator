import {useState} from 'react';

const WINDOWS:[string,number][]=[['2 s',2e9],['200 ms',2e8],['20 ms',2e7],['2 ms',2e6],['200 µs',2e5]];

// Edge traces recorded by the backend for probed endpoints (time in simulated ns).
export function LogicAnalyzer({probes,now,hover,onProbes}:{probes:Record<string,[number,number|null][]>;now:number;hover:string|null;
 onProbes:(endpoints:string[])=>void}){
 const [windowNs,setWindowNs]=useState(2e8);
 const endpoints=Object.keys(probes);
 const width=300,row=34;
 const x=(t:number)=>Math.max(0,Math.min(width,width-(now-t)/windowNs*width));
 return <div className="logic" role="tabpanel" aria-label="Logic analyzer">
  <div className="serial-bar">
   <select aria-label="Time window" value={windowNs} onChange={e=>setWindowNs(Number(e.target.value))}>
    {WINDOWS.map(([label,ns])=><option key={ns} value={ns}>{label}</option>)}</select>
   <button disabled={!hover||endpoints.includes(hover)||endpoints.length>=8} onClick={()=>hover&&onProbes([...endpoints,hover])}
    title="Hover a pin or hole on the bench, then click">+ Probe {hover??'(hover a pin)'}</button>
  </div>
  {!endpoints.length&&<p className="doctor-empty">Hover a pin, hole or header contact on the bench and add it as a probe to record its logic level over time (up to 8 channels).</p>}
  {endpoints.map(endpoint=>{
   const trace=probes[endpoint];
   let path='',last:number|null=null;
   const visible=trace.filter(([t])=>now-t<windowNs);
   const before=trace.filter(([t])=>now-t>=windowNs).pop();
   const start=before?before[1]:visible[0]?.[1]??null;
   const y=(level:number|null)=>level==null?row/2:level?6:row-6;
   path=`M0 ${y(start)}`;last=start;
   for(const [t,level] of visible){const px=x(t).toFixed(1);path+=` L${px} ${y(last)} L${px} ${y(level)}`;last=level;}
   path+=` L${width} ${y(last)}`;
   const edges=visible.length;
   return <figure key={endpoint} className="logic-row">
    <figcaption><b>{endpoint}</b> <span>{last==null?'float':last?'HIGH':'LOW'} · {edges} edge{edges===1?'':'s'}</span>
     <button aria-label={`Remove probe ${endpoint}`} onClick={()=>onProbes(endpoints.filter(e=>e!==endpoint))}>×</button></figcaption>
    <svg viewBox={`0 0 ${width} ${row}`} preserveAspectRatio="none" role="img" aria-label={`Waveform of ${endpoint}`}>
     <path d={path} fill="none" stroke="#6cdaa8" strokeWidth="1.5" vectorEffect="non-scaling-stroke"/>
    </svg>
   </figure>;
  })}
 </div>;
}
