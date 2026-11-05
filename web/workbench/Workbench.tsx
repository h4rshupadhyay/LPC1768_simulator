import {useCallback,useEffect,useMemo,useRef,useState} from 'react';
import {api} from '../api';
import type {Info,Layout,State} from '../types';
import type {ViewState} from '../viewState';
import type {CircuitState,EndpointInfo,Finding,PartSpec,PartState,Placement,Target,TerminalState} from './types';
import {Scene,type Pick,type View} from './Scene';
import {searchParts,type Filters} from './search';
import {LogicAnalyzer} from './LogicAnalyzer';
import {PITCH,holeIndex,partPins} from './geometry';
import './workbench.css';

const WIRE_COLORS=['#e53935','#1e88e5','#fdd835','#43a047','#fb8c00','#8e24aa','#212121','#f5f5f5'];
const SEVERITY_ORDER:Record<string,number>={damaged:0,'damage-risk':1,stress:2,warning:3,info:4};
const SEVERITY_LABEL:Record<string,string>={damaged:'Damaged','damage-risk':'Will damage',stress:'Overstressed',warning:'Problem',info:'Note'};

interface Props {info:Info;layout:Layout;state:ViewState&{circuit?:CircuitState;terminals?:Record<string,TerminalState>;target?:Target;timing?:string;speed?:number;floating?:string};
 publish:(s:State)=>void;control:(action:string)=>void;runtimeControls:React.ReactNode;compileSource:(code:string)=>Promise<void>}

interface BenchExample {id:string;title:string;description:string;timing:string;target:Target}

export function Workbench({info,layout,state,publish,control,runtimeControls,compileSource}:Props){
 const [examples,setExamples]=useState<BenchExample[]>([]);
 const [exampleNote,setExampleNote]=useState('');
 const [specs,setSpecs]=useState<PartSpec[]>([]);
 const [query,setQuery]=useState(''),[filters,setFilters]=useState<Filters>({});
 const [placing,setPlacing]=useState<{spec:PartSpec;moving?:string;placement:Placement}|null>(null);
 const [pendingWire,setPendingWire]=useState<string|null>(null);
 const [wireColor,setWireColor]=useState(WIRE_COLORS[0]);
 const [selected,setSelected]=useState<string|null>(null);
 const [selectedWire,setSelectedWire]=useState<[string,string]|null>(null);
 const [hover,setHover]=useState<string|null>(null),[probe,setProbe]=useState<EndpointInfo|null>(null);
 const [view,setView]=useState<View>('iso');
 const [panel,setPanel]=useState<'doctor'|'serial'|'inspect'|'logic'>('doctor');
 const [lastHover,setLastHover]=useState<string|null>(null);
 useEffect(()=>{if(hover)setLastHover(hover);},[hover]);
 const [error,setError]=useState('');
 const [highlight,setHighlight]=useState<Set<string>>(new Set());
 const [detail,setDetail]=useState<PartSpec|null>(null);
 const history=useRef<unknown[]>([]),future=useRef<unknown[]>([]);
 const target=(state.target??'als') as Target;
 const circuit=state.circuit??{parts:[],wires:[],findings:[],damageMode:'realistic',version:0};
 const specMap=useMemo(()=>Object.fromEntries(specs.map(s=>[s.kind,s])),[specs]);

 useEffect(()=>{api<{parts:PartSpec[]}>('/api/parts').then(r=>setSpecs(r.parts)).catch(e=>setError(String(e.message)));},[]);
 useEffect(()=>{api<{examples:BenchExample[]}>('/api/bench-examples').then(r=>setExamples(r.examples)).catch(()=>{});},[]);

 const loadExample=async(id:string)=>{
  if(!id)return;
  try{
   const example=await api<{source:string;project:unknown;timing:string;title:string}>(`/api/bench-examples/${id}`);
   await call('/api/settings',{timing:example.timing},false);
   await circuitCall({action:'load',project:example.project});
   await compileSource(example.source);
   setExampleNote(`${example.title}: circuit wired and firmware compiled. Press Run.`);
  }catch(e){setError((e as Error).message);}
 };

 const call=useCallback(async(path:string,data:unknown,record=true)=>{
  try{
   if(record&&path==='/api/circuit'){
    history.current.push(await api('/api/project'));
    if(history.current.length>40)history.current.shift();
    future.current=[];
   }
   const result=await api<any>(path,data);
   publish(result.state??result);setError('');
   return result;
  }catch(e){setError((e as Error).message);return null;}
 },[publish]);
 const circuitCall=(data:unknown,record=true)=>call('/api/circuit',data,record);

 const undo=async()=>{
  const previous=history.current.pop();if(!previous)return;
  future.current.push(await api('/api/project'));
  await circuitCall({action:'load',project:previous},false);
 };
 const redo=async()=>{
  const next=future.current.pop();if(!next)return;
  history.current.push(await api('/api/project'));
  await circuitCall({action:'load',project:next},false);
 };

 // Pointer-driven placement: snap to the 0.1" grid; pins dropped onto holes mount the part.
 const snap=(x:number,z:number)=>[Math.round(x/PITCH)*PITCH,Math.round(z/PITCH)*PITCH];
 const mountFor=(spec:PartSpec,placement:Placement,exclude?:string)=>{
  if(spec.kind==='breadboard')return undefined;
  const index=holeIndex(circuit.parts.filter(p=>p.id!==exclude));
  const mount:Record<string,string>={};
  for(const [pin,[x,z]] of Object.entries(partPins(spec,placement))){
   const hole=index.find(x,z);if(!hole)return undefined;
   mount[pin]=`${hole.board}.${hole.hole}`;
  }
  return mount;
 };
 const onBench=(x:number,z:number,clicked:boolean)=>{
  if(!placing)return;
  const [sx,sz]=snap(x,z);
  const placement={...placing.placement,x:sx,z:sz};
  if(!clicked){if(sx!==placing.placement.x||sz!==placing.placement.z)setPlacing({...placing,placement});return;}
  const mount=mountFor(placing.spec,placement,placing.moving);
  const done=placing.moving
   ?circuitCall({action:'move',id:placing.moving,placement,mount:mount??{}})
   :circuitCall({action:'add',type:placing.spec.kind,placement,mount});
  void done.then(r=>{if(r){setPlacing(null);if(r.info?.id)setSelected(r.info.id);}});
 };
 const onPin=(pick:Pick)=>{
  if(placing)return;
  if(!pendingWire){setPendingWire(pick.endpoint);return;}
  if(pendingWire===pick.endpoint){setPendingWire(null);return;}
  void circuitCall({action:'connect',a:pendingWire,b:pick.endpoint,color:wireColor}).then(()=>setPendingWire(null));
 };
 const onKit=(action:any)=>{
  if(action.action==='jumper-cycle'){
   const options=info.board.jumpers[action.name].states;
   const value=options[(options.indexOf(state.jumpers[action.name])+1)%options.length];
   void call('/api/physical',{action:'jumper',name:action.name,value},false);
  }else void call('/api/physical',action,false);
 };

 useEffect(()=>{
  const key=(e:KeyboardEvent)=>{
   if((e.target as HTMLElement)?.closest('input,textarea,select'))return;
   if(e.key==='Escape'){setPlacing(null);setPendingWire(null);}
   if((e.key==='r'||e.key==='R')&&placing)setPlacing({...placing,placement:{...placing.placement,rot:(placing.placement.rot+1)%4}});
   if((e.key==='Delete'||e.key==='Backspace')&&!placing){
    if(selectedWire){void circuitCall({action:'disconnect',a:selectedWire[0],b:selectedWire[1]});setSelectedWire(null);}
    else if(selected){void circuitCall({action:'remove',id:selected});setSelected(null);}
   }
   if(e.ctrlKey&&e.key==='z'){e.preventDefault();void undo();}
   if(e.ctrlKey&&e.key==='y'){e.preventDefault();void redo();}
  };
  window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key);
 });

 // Multimeter probe: inspect the hovered endpoint (debounced).
 useEffect(()=>{
  if(!hover){setProbe(null);return;}
  const t=setTimeout(()=>{api<{info:EndpointInfo}>('/api/circuit',{action:'inspect',endpoint:hover}).then(r=>setProbe(r.info)).catch(()=>setProbe(null));},120);
  return()=>clearTimeout(t);
 },[hover,state.circuit?.version]);

 const results=useMemo(()=>searchParts(specs,query,filters),[specs,query,filters]);
 const categories=useMemo(()=>[...new Set(specs.map(s=>s.category))].sort(),[specs]);
 const interfaces=useMemo(()=>[...new Set(specs.flatMap(s=>s.interfaces))].sort(),[specs]);
 const selectedPart=circuit.parts.find(p=>p.id===selected)??null;
 const findings=[...circuit.findings].sort((a,b)=>SEVERITY_ORDER[a.severity]-SEVERITY_ORDER[b.severity]);
 const severe=findings.filter(f=>f.severity!=='info').length;

 const startPlacing=(spec:PartSpec)=>{setPendingWire(null);setPlacing({spec,placement:{x:40,z:60,rot:0}});};
 const saveProject=async()=>{
  const project=await api('/api/project');
  const source=localStorage.getItem('lpc-lab-source')??'';
  const blob=new Blob([JSON.stringify({format:'lpc1768-bench/1',circuit:project,source},null,1)],{type:'application/json'});
  const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='bench-project.json';a.click();URL.revokeObjectURL(a.href);
 };
 const loadProject=async(file:File)=>{
  try{
   const data=JSON.parse(await file.text());
   if(data.source)localStorage.setItem('lpc-lab-source',data.source);
   await circuitCall({action:'load',project:data.circuit??data});
  }catch(e){setError(`Could not load project: ${(e as Error).message}`);}
 };
 const fileInput=useRef<HTMLInputElement>(null);

 return <section className="bench" aria-label="Workbench">
  <div className="bench-toolbar">
   <label>Example <select aria-label="Load a bench example" value="" onChange={e=>{void loadExample(e.target.value);}}>
    <option value="">Choose…</option>{examples.map(x=><option key={x.id} value={x.id} title={x.description}>{x.title}</option>)}</select></label>
   <label>Target <select aria-label="Target board" value={target} onChange={e=>{void call('/api/settings',{target:e.target.value},false);}}>
    <option value="als">ALS LPC1768 kit</option><option value="mbed">mbed LPC1768</option><option value="bare">Bare LPC1768</option></select></label>
   <label>Timing <select aria-label="Timing mode" value={state.timing??'realtime'} onChange={e=>{void call('/api/settings',{timing:e.target.value},false);}}>
    <option value="realtime">Real-time</option><option value="precise">Precise (µs)</option></select></label>
   {state.timing==='precise'&&<span className="bench-speed" title="Simulated time per wall-clock second">{Math.round((state.speed??1)*100)}% speed</span>}
   <div className="bench-views" role="group" aria-label="Camera view">
    {(['iso','top','front','board','focus'] as View[]).map(v=><button key={v} aria-pressed={view===v} onClick={()=>setView(v)}>{{iso:'3D',top:'Top',front:'Front',board:'Board',focus:'Focus'}[v]}</button>)}
   </div>
   <div className="bench-colors" role="group" aria-label="Wire colour">{WIRE_COLORS.map(c=><button key={c} aria-label={`Wire colour ${c}`} aria-pressed={wireColor===c} style={{background:c}} onClick={()=>setWireColor(c)}/>)}</div>
   <button onClick={()=>void undo()} title="Undo (Ctrl+Z)">↶</button><button onClick={()=>void redo()} title="Redo (Ctrl+Y)">↷</button>
   <button onClick={()=>void saveProject()}>Save project</button>
   <button onClick={()=>fileInput.current?.click()}>Open…</button>
   <input ref={fileInput} type="file" accept=".json" hidden onChange={e=>{const f=e.target.files?.[0];if(f)void loadProject(f);e.target.value='';}}/>
   <button onClick={()=>{if(confirm('Remove every part and wire from the bench?'))void circuitCall({action:'clear'});}}>Clear bench</button>
   {runtimeControls}
  </div>
  <div className="bench-body">
   <aside className="bench-catalog" aria-label="Component catalogue">
    <input aria-label="Search components" placeholder="Search: “distance”, “oled”, “5V relay”…" value={query} onChange={e=>setQuery(e.target.value)}/>
    <div className="bench-filters">
     <select aria-label="Category" value={filters.category??''} onChange={e=>setFilters({...filters,category:e.target.value||undefined})}>
      <option value="">All categories</option>{categories.map(c=><option key={c}>{c}</option>)}</select>
     <select aria-label="Interface" value={filters.interface??''} onChange={e=>setFilters({...filters,interface:e.target.value||undefined})}>
      <option value="">Any interface</option>{interfaces.map(c=><option key={c}>{c}</option>)}</select>
     <select aria-label="Compatibility" value={filters.compat??''} onChange={e=>setFilters({...filters,compat:e.target.value||undefined})}>
      <option value="">Any compatibility</option><option value="direct">Works directly</option><option value="needs">Needs extra parts</option></select>
    </div>
    <ul className="bench-results">{results.map(spec=><li key={spec.kind}>
     <button className="bench-card" onClick={()=>startPlacing(spec)} aria-label={`Place ${spec.name}`}>
      <strong>{spec.name}</strong><span>{spec.category} · {spec.interfaces.join(', ')||'—'}</span>
      <em className={`compat compat-${spec.compat.startsWith('direct')?'ok':'warn'}`}>{spec.compatText}</em>
     </button>
     <button className="bench-info" aria-label={`About ${spec.name}`} onClick={()=>setDetail(spec)}>i</button>
    </li>)}</ul>
   </aside>
   <div className="bench-stage">
    {specs.length>0&&<Scene target={target} layout={layout} state={state} specs={specMap} parts={circuit.parts} wires={circuit.wires}
     view={view} selected={selected} highlight={highlight} pendingWire={pendingWire}
     ghost={placing?{spec:placing.spec,placement:placing.placement}:null}
     onPin={onPin} onHover={setHover} onSelect={id=>{setSelected(id);setSelectedWire(null);if(id)setPanel('inspect');}}
     onBench={onBench} onWire={(a,b)=>{setSelectedWire([a,b]);setSelected(null);}} onKit={onKit} onReset={()=>control('reset')} hoverInfo={hover}/>}
    <div className="bench-hud" aria-live="polite">
     {placing&&<span>Placing <b>{placing.spec.name}</b> — click to drop, <kbd>R</kbd> rotates, <kbd>Esc</kbd> cancels. Pins over breadboard holes plug in.</span>}
     {pendingWire&&<span>Wire from <b>{pendingWire}</b>: click another pin or hole. <kbd>Esc</kbd> cancels.</span>}
     {selectedWire&&<span>Wire {selectedWire[0]} ↔ {selectedWire[1]} — <button onClick={()=>{void circuitCall({action:'disconnect',a:selectedWire[0],b:selectedWire[1]});setSelectedWire(null);}}>Remove wire</button></span>}
     {probe&&<span className="bench-probe">⎓ {probe.endpoint}{probe.node!==probe.endpoint?` (${probe.node})`:''}: <b>{probe.volts!=null?`${probe.volts.toFixed(3)} V`:probe.level==null?'floating':probe.level?'HIGH':'LOW'}</b>
      {probe.function&&<> · {probe.function}</>}</span>}
     {exampleNote&&<span>{exampleNote} <button onClick={()=>setExampleNote('')}>×</button></span>}
     {error&&<span role="alert" className="error">{error}</span>}
    </div>
   </div>
   <aside className="bench-side" aria-label="Bench panels">
    <div className="bench-tabs" role="tablist">
     <button role="tab" aria-selected={panel==='doctor'} onClick={()=>setPanel('doctor')}>Circuit Doctor{severe?` (${severe})`:''}</button>
     <button role="tab" aria-selected={panel==='inspect'} onClick={()=>setPanel('inspect')}>Inspector</button>
     <button role="tab" aria-selected={panel==='serial'} onClick={()=>setPanel('serial')}>Serial</button>
     <button role="tab" aria-selected={panel==='logic'} onClick={()=>setPanel('logic')}>Logic</button>
    </div>
    {panel==='doctor'&&<Doctor findings={findings} damageMode={circuit.damageMode} floating={state.floating??'low'}
     onApply={patch=>void circuitCall({action:'apply',patch})} onHighlight={f=>setHighlight(new Set(f?.parts??[]))}
     onMode={mode=>void circuitCall({action:'damage-mode',mode},false)} onFloating={mode=>void call('/api/settings',{floating:mode},false)}/>}
    {panel==='inspect'&&<Inspector part={selectedPart} spec={selectedPart?specMap[selectedPart.type]:undefined}
     findings={findings.filter(f=>selectedPart&&f.parts.includes(selectedPart.id))}
     onStimulus={(name,value)=>void circuitCall({action:'stimulus',id:selectedPart!.id,name,value},false)}
     onProps={props=>void circuitCall({action:'props',id:selectedPart!.id,props})}
     onRemove={()=>{void circuitCall({action:'remove',id:selectedPart!.id});setSelected(null);}}
     onMove={()=>{if(selectedPart&&specMap[selectedPart.type])setPlacing({spec:specMap[selectedPart.type],moving:selectedPart.id,placement:{x:selectedPart.placement.x??0,z:selectedPart.placement.z??0,rot:selectedPart.placement.rot??0}});}}
     onReplace={()=>void circuitCall({action:'apply',patch:[{op:'replace',id:selectedPart!.id}]})}/>}
    {panel==='serial'&&<Serial terminals={state.terminals??{}} parts={circuit.parts} call={call}/>}
    {panel==='logic'&&<LogicAnalyzer probes={circuit.probes??{}} now={circuit.now??0} hover={lastHover}
     onProbes={endpoints=>void circuitCall({action:'probes',endpoints},false)}/>}
   </aside>
  </div>
  {detail&&<PartDetail spec={detail} target={target} onClose={()=>setDetail(null)} onPlace={()=>{startPlacing(detail);setDetail(null);}}/>}
 </section>;
}

function Doctor({findings,damageMode,floating,onApply,onHighlight,onMode,onFloating}:{findings:Finding[];damageMode:string;floating:string;
 onApply:(patch:unknown[])=>void;onHighlight:(f:Finding|null)=>void;onMode:(m:string)=>void;onFloating:(m:string)=>void}){
 return <div className="doctor" role="tabpanel" aria-label="Circuit Doctor">
  <div className="doctor-settings">
   <label><input type="checkbox" checked={damageMode==='realistic'} onChange={e=>onMode(e.target.checked?'realistic':'warn')}/> Realistic damage</label>
   <label><input type="checkbox" checked={floating==='random'} onChange={e=>onFloating(e.target.checked?'random':'low')}/> Random floating inputs</label>
  </div>
  {!findings.length&&<p className="doctor-empty">No problems found. The Doctor checks wiring, supply and pin voltages, currents and firmware settings as the circuit runs.</p>}
  {findings.map(f=><article key={f.key} className={`finding finding-${f.severity}`} onMouseEnter={()=>onHighlight(f)} onMouseLeave={()=>onHighlight(null)}>
   <header><span className="finding-severity">{SEVERITY_LABEL[f.severity]}</span><h3>{f.title}</h3></header>
   <p>{f.what}</p>
   {f.why&&<p className="finding-why"><b>Why:</b> {f.why}</p>}
   {f.consequence&&<p className="finding-consequence"><b>Result:</b> {f.consequence}</p>}
   {f.fixes.map((fix,i)=><div key={i} className="fix">
    <b>Fix: {fix.label}</b>
    <ul>{fix.steps.map((s,j)=><li key={j}>{s}</li>)}</ul>
    {fix.apply&&<button className="run" onClick={()=>onApply(fix.apply!)}>Apply fix</button>}
   </div>)}
  </article>)}
 </div>;
}

function Inspector({part,spec,findings,onStimulus,onProps,onRemove,onMove,onReplace}:{part:PartState|null;spec?:PartSpec;findings:Finding[];
 onStimulus:(name:string,value:number)=>void;onProps:(p:Record<string,unknown>)=>void;onRemove:()=>void;onMove:()=>void;onReplace:()=>void}){
 if(!part)return <div className="inspector" role="tabpanel"><p className="doctor-empty">Select a part on the bench to see its pins, live voltages and inputs. Hover any pin or hole to probe it.</p></div>;
 const name=spec?.name??part.type;
 return <div className="inspector" role="tabpanel" aria-label={`${name} inspector`}>
  <h3>{name} <code>{part.id}</code></h3>
  {spec&&<p className="inspector-desc">{spec.description}</p>}
  {part.damaged&&<div className="finding finding-damaged"><b>Damaged.</b> {part.damaged} <button onClick={onReplace}>Replace part</button></div>}
  {spec&&Object.keys(spec.defaults).length>0&&<fieldset><legend>Properties</legend>{Object.entries(spec.defaults).map(([key,def])=>{
   const value=part.props[key]??def,choices=spec.choices[key];
   return <label key={key}>{key}{choices?<select value={String(value)} onChange={e=>{const v=choices.find(c=>String(c)===e.target.value);onProps({[key]:v});}}>
    {choices.map(c=><option key={String(c)} value={String(c)}>{String(c)}</option>)}</select>
    :typeof def==='boolean'?<input type="checkbox" checked={!!value} onChange={e=>onProps({[key]:e.target.checked})}/>
    :typeof def==='number'?<input type="number" defaultValue={Number(value)} step="any" onBlur={e=>onProps({[key]:Number(e.target.value)})}/>
    :<input defaultValue={String(value)} onBlur={e=>onProps({[key]:e.target.value})}/>}</label>;})}</fieldset>}
  {spec&&Object.keys(spec.stimuli).length>0&&<fieldset><legend>Environment / inputs</legend>{Object.entries(spec.stimuli).map(([name,s])=>{
   const value=part.stimuli[name]??s.default,binary=s.min===0&&s.max===1&&Number.isInteger(s.default);
   return <label key={name}>{s.label}{binary?<input type="checkbox" checked={!!value} onChange={e=>onStimulus(name,e.target.checked?1:0)}
     onPointerDown={()=>{if(part.type==='button')onStimulus(name,1);}} onPointerUp={()=>{if(part.type==='button')onStimulus(name,0);}}/>
    :<><input type="range" min={s.min} max={s.max} step={(s.max-s.min)/500} value={value} onChange={e=>onStimulus(name,Number(e.target.value))}/>
     <output>{Number(value).toFixed(s.max-s.min>50?0:2)} {s.unit}</output></>}</label>;})}</fieldset>}
  <fieldset><legend>Pins</legend><table className="inspector-pins"><tbody>{Object.entries(part.pins).map(([pin,v])=><tr key={pin}>
   <td>{pin}</td><td>{v==null?'—':`${v.toFixed(3)} V`}</td><td>{part.mount[pin]??''}</td></tr>)}</tbody></table></fieldset>
  {Object.keys(part.state).length>0&&<fieldset><legend>State</legend><pre className="inspector-state">{JSON.stringify(part.state,(k,v)=>k==='fb'||k==='text'?undefined:typeof v==='number'?Math.round(v*1000)/1000:v,1)}</pre></fieldset>}
  {findings.length>0&&<p className="inspector-warn">{findings.length} Doctor finding{findings.length>1?'s':''} for this part.</p>}
  <div className="inspector-actions"><button onClick={onMove}>Move / rotate</button><button onClick={onRemove}>Remove</button></div>
 </div>;
}

function Serial({terminals,parts,call}:{terminals:Record<string,TerminalState>;parts:PartState[];call:(path:string,data:unknown,record?:boolean)=>Promise<unknown>}){
 const options=[...Object.entries(terminals).map(([k,t])=>({key:k,name:t.name,t})),
  ...parts.filter(p=>p.state&&'text' in p.state).map(p=>({key:p.id,name:String(p.state.name??p.id),t:p.state as unknown as TerminalState}))];
 const [key,setKey]=useState(options[0]?.key??'0');
 const [text,setText]=useState(''),[ending,setEnding]=useState('\r\n');
 const current=options.find(o=>o.key===key)??options[0];
 const out=useRef<HTMLPreElement>(null);
 useEffect(()=>{if(out.current)out.current.scrollTop=out.current.scrollHeight;},[current?.t.text]);
 if(!current)return <div className="serial" role="tabpanel"><p className="doctor-empty">No serial terminals.</p></div>;
 return <div className="serial" role="tabpanel" aria-label="Serial monitor">
  <div className="serial-bar">
   <select aria-label="Terminal" value={current.key} onChange={e=>setKey(e.target.value)}>{options.map(o=><option key={o.key} value={o.key}>{o.name}</option>)}</select>
   <select aria-label="Baud rate" value={current.t.baud} onChange={e=>void call('/api/serial',{action:'baud',terminal:current.key,baud:Number(e.target.value)},false)}>
    {[1200,2400,4800,9600,19200,38400,57600,115200].map(b=><option key={b}>{b}</option>)}</select>
   <button onClick={()=>void call('/api/serial',{action:'clear',terminal:current.key},false)}>Clear</button>
  </div>
  {current.t.mismatch&&<p className="inspector-warn">Bytes arrive at a different baud rate than {current.t.baud}: the text is garbled.</p>}
  <pre ref={out} className="serial-out" aria-label="Received text">{current.t.text||'(nothing received yet)'}</pre>
  <form className="serial-send" onSubmit={e=>{e.preventDefault();void call('/api/serial',{action:'send',terminal:current.key,text:text+ending},false);setText('');}}>
   <input aria-label="Text to send" value={text} onChange={e=>setText(e.target.value)} placeholder="Type and press Enter"/>
   <select aria-label="Line ending" value={ending} onChange={e=>setEnding(e.target.value)}><option value={'\r\n'}>CR LF</option><option value={'\n'}>LF</option><option value="">None</option></select>
   <button type="submit">Send</button>
  </form>
 </div>;
}

const WIRING:Record<Target,string>={
 als:'On the ALS kit, use jumper wires from header pins (e.g. CND.1 = P0.23) or the PWR tap (3V3 / 5V / GND) to the breadboard.',
 mbed:'On the mbed module, use pins p5–p30, VOUT (3.3 V, ~40 mA), VU (5 V from USB) and GND.',
 bare:'On the bare chip every LQFP100 pad is available; 3V3 and GND are on the header ends.',
};

function PartDetail({spec,target,onClose,onPlace}:{spec:PartSpec;target:Target;onClose:()=>void;onPlace:()=>void}){
 return <div className="bench-modal" role="dialog" aria-modal="true" aria-label={spec.name} onClick={onClose}>
  <div className="bench-modal-body" onClick={e=>e.stopPropagation()}>
   <h2>{spec.name}</h2>
   <p className="compat">{spec.compatText}</p>
   <p>{spec.description}</p>
   <dl><dt>Category</dt><dd>{spec.category}</dd><dt>Interfaces</dt><dd>{spec.interfaces.join(', ')||'—'}</dd>
    <dt>Supply</dt><dd>{spec.supply}</dd><dt>Pins</dt><dd>{spec.pins.join(' · ')||'—'}</dd>
    {spec.ratings.supply&&<><dt>Ratings</dt><dd>{String(spec.ratings.supply[2])}–{String(spec.ratings.supply[3])} V, absolute max {String(spec.ratings.supply[4])} V</dd></>}
    <dt>Also known as</dt><dd>{spec.aliases.join(', ')}</dd></dl>
   <p className="inspector-desc">{WIRING[target]}</p>
   <div className="inspector-actions"><button className="run" onClick={onPlace}>Place on bench</button><button onClick={onClose}>Close</button></div>
  </div>
 </div>;
}
