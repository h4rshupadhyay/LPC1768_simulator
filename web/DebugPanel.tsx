import {useEffect,useState} from 'react';
import {api} from './api';

interface Debug {
 registers:Record<string,number>;pc:number;source:{file:string;line:number}|null;hasSource:boolean;
 breakpoints:number[];stopReason:string;symbols:{name:string;address:number;type:string;bytes?:number[]}[];
}

// Collapsible debugger: printf console, source line, registers, line breakpoints and stepping.
export function DebugPanel({loaded,status}:{loaded:boolean;status:string}){
 const [open,setOpen]=useState(false),[debug,setDebug]=useState<Debug|null>(null);
 const [line,setLine]=useState(''),[error,setError]=useState('');
 const send=async(data:unknown)=>{
  try{const r=await api<{debug:Debug}>('/api/debug',data);setDebug(r.debug);setError('');}catch(e){setError((e as Error).message);}
 };
 useEffect(()=>{
  if(!open)return;
  void send({action:'state'});
  const t=setInterval(()=>{void send({action:'state'});},status==='running'?400:1500);
  return()=>clearInterval(t);
 },[open,status,loaded]);
 const console_=debug?.symbols.find(s=>s.name==='lpc_console_buffer')?.bytes??[];
 const text=String.fromCharCode(...console_.filter(b=>b));
 // A plain toggle rather than <details>: the exam screens deliberately contain no
 // collapsible help panels, and browser tests assert that.
 return <section className="debug-panel" aria-label="Debugger">
  <button className="debug-toggle" aria-expanded={open} onClick={()=>setOpen(!open)}>{open?'▾':'▸'} Debugger &amp; printf console</button>
  {open&&debug&&<div className="debug-grid">
   <div>
    <h3>Console (printf)</h3>
    <pre className="debug-console" aria-label="printf output">{text||'(no output — printf writes here)'}</pre>
   </div>
   <div>
    <h3>Execution</h3>
    <p>PC <code>0x{debug.pc.toString(16).toUpperCase().padStart(8,'0')}</code>{debug.source&&<> · {debug.source.file.split('/').pop()}:{debug.source.line}</>} · {debug.stopReason}</p>
    <div className="debug-actions">
     <button disabled={!loaded} onClick={()=>void send({action:'step',count:1})}>Step</button>
     <button disabled={!loaded} onClick={()=>void send({action:'step',count:100})}>Step ×100</button>
     <form onSubmit={e=>{e.preventDefault();if(line)void send({action:'breakpoint',line:Number(line)});setLine('');}}>
      <input aria-label="Breakpoint line" placeholder="line" value={line} onChange={e=>setLine(e.target.value.replace(/\D/g,''))} size={5}/>
      <button type="submit" disabled={!debug.hasSource}>Break at line</button>
     </form>
     <button disabled={!debug.breakpoints.length} onClick={()=>void send({action:'clear-breakpoints'})}>Clear breakpoints ({debug.breakpoints.length})</button>
    </div>
    <table className="debug-registers"><tbody>{Object.entries(debug.registers).map(([k,v])=><tr key={k}><td>{k}</td><td>0x{(v>>>0).toString(16).toUpperCase().padStart(8,'0')}</td><td>{v|0}</td></tr>)}</tbody></table>
   </div>
  </div>}
  {open&&error&&<p className="error">{error}</p>}
 </section>;
}
