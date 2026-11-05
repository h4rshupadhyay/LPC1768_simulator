import {Suspense,lazy,useCallback,useEffect,useLayoutEffect,useRef,useState} from 'react';
import {api} from './api';
import {Board} from './Board';
import {ExerciseSolution} from './ExerciseSolution';
import {CSource} from './CSource';
// three.js is large; only the Workbench screen loads it.
const Workbench=lazy(()=>import('./workbench/Workbench').then(m=>({default:m.Workbench})));
import {DebugPanel} from './DebugPanel';
import type {Info,State,Layout,Exercise} from './types';
import {reconcileViewState,type ViewState} from './viewState';

const DEFAULT_SOURCE=`#include <LPC17xx.h>

int main(void)
{
    SystemInit();
    SystemCoreClockUpdate();

    while (1) {
    }
}
`;

type Screen='board'|'bench'|'ide'|'labs';
const currentScreen=():Screen=>{
 const hash=window.location.hash.slice(1);
 return hash==='ide'||hash==='labs'||hash==='bench'?hash:'board';
};

export function App() {
 const [info,setInfo]=useState<Info|null>(null),[state,setState]=useState<ViewState|null>(null),[layout,setLayout]=useState<Layout|null>(null);
 const publishState=useCallback((snapshot:State)=>{
  setState(previous=>reconcileViewState(previous,snapshot));
 },[]);
 const [error,setError]=useState(''),[busy,setBusy]=useState(false);
 const [loadingHex,setLoadingHex]=useState(false);
 const [buildError,setBuildError]=useState('');
 const [exercise,setExercise]=useState(()=>localStorage.getItem('lpc-lab-exercise')||'lab7_sequence');
 const [source,setSource]=useState(()=>localStorage.getItem('lpc-lab-source')??DEFAULT_SOURCE);
 const [dirty,setDirty]=useState(true),[message,setMessage]=useState('');
 const [zoom,setZoom]=useState(100),[screen,setScreen]=useState<Screen>(currentScreen);
 const [hex,setHex]=useState<string|null>(null),[firmwareKind,setFirmwareKind]=useState<'c'|'hex'>('c');
 const queue=useRef<Promise<void>>(Promise.resolve()),revision=useRef(0),fileInput=useRef<HTMLInputElement>(null);
 const requestNumber=useRef(0),latestSource=useRef(source),previousScreen=useRef(screen);
 const firmwareBusy=useRef(false),selectedExercise=useRef(exercise);
 selectedExercise.current=exercise;
 const sourceEditor=useRef<HTMLTextAreaElement>(null),lineNumbers=useRef<HTMLPreElement>(null),sourceHighlight=useRef<HTMLPreElement>(null);
 const editorPosition=useRef({start:0,end:0,top:0,left:0});
 const pendingEditorSelection=useRef<{start:number;end:number;direction:'forward'|'backward'|'none'}|null>(null);
 const attachSourceEditor=useCallback((editor:HTMLTextAreaElement|null)=>{
  const previous=sourceEditor.current;
  if(previous)editorPosition.current={start:previous.selectionStart,end:previous.selectionEnd,top:previous.scrollTop,left:previous.scrollLeft};
  sourceEditor.current=editor;
  if(editor){
   const saved=editorPosition.current;
   editor.setSelectionRange(saved.start,saved.end);
   editor.scrollTop=saved.top;editor.scrollLeft=saved.left;
  }
 },[]);
 const syncEditorScroll=()=>{
  const editor=sourceEditor.current,highlight=sourceHighlight.current;
  if(!editor)return;
  if(lineNumbers.current)lineNumbers.current.style.transform=`translateY(-${editor.scrollTop}px)`;
  if(highlight){
   // Match the text viewport, excluding native scrollbars on either axis.
   highlight.style.width=`${editor.clientWidth}px`;highlight.style.height=`${editor.clientHeight}px`;
   highlight.scrollTop=editor.scrollTop;highlight.scrollLeft=editor.scrollLeft;
  }
 };
 useLayoutEffect(()=>{
  const editor=sourceEditor.current,position=pendingEditorSelection.current;
  if(editor&&position!==null){
   editor.setSelectionRange(position.start,position.end,position.direction);
   pendingEditorSelection.current=null;
  }
  syncEditorScroll();
 },[source,screen,info,layout]);
 useLayoutEffect(()=>{
  const editor=sourceEditor.current;
  if(!editor)return;
  const observer=new ResizeObserver(syncEditorScroll);
  observer.observe(editor);
  return()=>observer.disconnect();
 },[screen,info,layout]);

 useEffect(()=>{
  let active=true;
  Promise.all([api<Info>('/api/info'),api<State>('/api/state'),api<Layout>('/board/layout.json')])
   .then(([i,s,l])=>{if(active){setInfo(i);publishState(s);setLayout(l);}}).catch(e=>{if(active)setError(String(e.message));});
  return()=>{active=false;};
 },[]);
 useEffect(()=>{localStorage.setItem('lpc-lab-source',source);},[source]);
 useEffect(()=>{localStorage.setItem('lpc-lab-exercise',exercise);},[exercise]);
 useEffect(()=>{
  document.title=`LPC1768 · ${screen==='board'?'Board':screen==='bench'?'Workbench':screen==='ide'?'IDE':'Lab exercises'}`;
 },[screen]);
 useEffect(()=>{
  const navigate=()=>{
   const next=currentScreen();
   if(previousScreen.current==='board'&&next!=='board')void physical({action:'release-inputs'});
   previousScreen.current=next;setScreen(next);
  };
  window.addEventListener('hashchange',navigate);
  return()=>window.removeEventListener('hashchange',navigate);
 },[]);
 useEffect(()=>{
  let cancelled=false,polling=false;
  const timer=setInterval(async()=>{
   if(polling)return;
   polling=true;
   const rev=revision.current;
   try {const s=await api<State>('/api/state');if(!cancelled&&rev===revision.current)publishState(s);}
   catch(e){if(!cancelled)setError((e as Error).message);}
   finally{polling=false;}
  },50);
  const release=()=>{void physical({action:'release-inputs'});};
  window.addEventListener('blur',release);
  return()=>{cancelled=true;clearInterval(timer);window.removeEventListener('blur',release);};
 },[]);

 const physical=(data:unknown):Promise<void>=>{
  revision.current++;
  queue.current=queue.current.then(async()=>{
   try{publishState(await api<State>('/api/physical',data));setError('');}
   catch(e){setError((e as Error).message);}
  });
  return queue.current;
 };
 const control=async(action:string)=>{
  revision.current++;
  try{await queue.current;publishState(await api<State>('/api/control',{action}));setError('');}
  catch(e){setError((e as Error).message);}
 };
 const compile=async(override?:string)=>{
  if(firmwareBusy.current)return;
  firmwareBusy.current=true;
  setBusy(true);setError('');setBuildError('');setMessage('Compiling…');
  requestNumber.current++;
  revision.current++;
  const code=override??source;
  if(override!==undefined){latestSource.current=override;setSource(override);setFirmwareKind('c');}
  try{
   const result=await api<{state:State;hex:string;diagnostics:string}>('/api/compile',{source:code});
   publishState(result.state);setHex(result.hex);setDirty(latestSource.current!==code);setFirmwareKind('c');setMessage(result.diagnostics);
  }catch(e){setBuildError((e as Error).message);setMessage('Compilation failed.');}
  finally{firmwareBusy.current=false;setBusy(false);}
 };
 const upload=async(file:File)=>{
  if(firmwareBusy.current)return;
  const number=++requestNumber.current;
  setError('');setBuildError('');
  try{
   if(file.size>3_000_000)throw new Error('File is too large (maximum 3 MB).');
   const text=await file.text();
   if(number!==requestNumber.current)return;
   if(/\.hex$/i.test(file.name)){
    firmwareBusy.current=true;setBusy(true);setLoadingHex(true);
    try {
    revision.current++;
    const uploaded=await api<State>('/api/firmware',{hex:text,name:file.name});
    if(number!==requestNumber.current)return;
    publishState(uploaded);
    setHex(text);setFirmwareKind('hex');setDirty(false);setMessage(`Loaded ${file.name}.`);
    } finally {
     firmwareBusy.current=false;setBusy(false);setLoadingHex(false);
    }
   }else if(/\.c$/i.test(file.name)){
    latestSource.current=text;setSource(text);setDirty(true);setFirmwareKind('c');setMessage(`Opened ${file.name}.`);
   }else throw new Error('Choose a .c or .hex file.');
  }catch(e){if(number===requestNumber.current)setError((e as Error).message);}
 };
 const openSolution=(code:string,selected:Exercise)=>{
  if(firmwareBusy.current||selected.id!==selectedExercise.current)return;
  requestNumber.current++;
  editorPosition.current={start:0,end:0,top:0,left:0};
  latestSource.current=code;setSource(code);setDirty(true);setFirmwareKind('c');
  setError('');setBuildError('');setMessage(`Opened ${selected.title} solution. Compile C to load it.`);
  window.location.hash='ide';
 };
 const download=(content:string,name:string)=>{
  const url=URL.createObjectURL(new Blob([content],{type:'text/plain'}));
  const a=document.createElement('a');a.href=url;a.download=name;a.click();URL.revokeObjectURL(url);
 };

 if(!info||!state||!layout)return <main className="loading"><h1>LPC1768 Virtual Lab</h1><p>{error||'Connecting…'}</p></main>;
 const spec=info.exercises.find(e=>e.id===exercise);
 const running=state.status==='running',runnable=state.loaded&&!busy&&!dirty&&state.status!=='error';
 const runtimeControls=<div className="runtime-controls">
  <button className="run" disabled={!runnable||running} onClick={()=>{void control(state.status==='paused'?'resume':'run');}}>{state.status==='paused'?'▶ Resume':'▶ Run'}</button>
  <button disabled={!running||busy} onClick={()=>{void control('pause');}}>Ⅱ Pause</button>
  <button disabled={!state.loaded||busy} onClick={()=>{void control('stop');}}>■ Stop</button>
  <button disabled={busy} onClick={()=>{void control('reset');}}>↺ Reset</button>
 </div>;
 const diagnosticText=state.error||message||(state.loaded?state.diagnostics:'');
 const diagnostics=(error||buildError||diagnosticText)?<div className="diagnostics" aria-label="Compiler and runtime messages">
  {error&&<pre role="alert" className="error">{error}</pre>}
  {buildError&&<pre role="alert" className="error">{buildError}</pre>}
  {diagnosticText&&<pre role="status">{diagnosticText}</pre>}
 </div>:null;

 return <div className={`app-shell ${screen}-view`}>
  <header className="app-header">
   <div className="identity"><div className="chip-logo">M3</div><h1>LPC1768 <span>Virtual Lab</span></h1></div>
   <nav className="screen-nav" aria-label="Workspace">
   <a href="#board" aria-current={screen==='board'?'page':undefined}>Board</a>
   <a href="#bench" aria-current={screen==='bench'?'page':undefined}>Workbench</a>
   <a href="#ide" aria-current={screen==='ide'?'page':undefined}>IDE</a>
   <a href="#labs" aria-current={screen==='labs'?'page':undefined}>Lab exercises</a>
   </nav>
   <div className="engine-state"><span className={`dot ${running?'green':state.status==='error'?'red':''}`}/><span>{state.status.toUpperCase()}</span></div>
  </header>
  <main className={`workspace ${screen}-screen`}>
   {screen==='board'&&<section className="board-panel panel" aria-label="Virtual board panel">
    <div className="board-toolbar">
    <div className="panel-heading"><h2>Virtual evaluation board</h2>
     <div className="board-zoom-tools">
      <button aria-label="Fit board to screen" onClick={()=>setZoom(100)}>Fit</button>
      <label className="zoom-control">Zoom <input aria-label="Board zoom" type="range" min="100" max="180" step="10" value={zoom} onChange={e=>setZoom(Number(e.target.value))}/></label>
     </div>
    </div>
    {runtimeControls}
    </div>
    <div className="board-workspace">
    <div className="zoom-container" style={{'--board-zoom':zoom/100} as React.CSSProperties}>
     <Board info={info} state={state} layout={layout} physical={physical} control={action=>{void control(action);}}/>
    </div>
    <aside className="board-sidebar" aria-label="Board connections and messages">
    <div className="board-connections">
     <div className="cable-tags" aria-label="Connected cables">{state.cables.map(([a,b])=><button key={a} onClick={()=>{void physical({action:'disconnect',header:a});}} aria-label={`Disconnect cable ${a} to ${b}`}>{a} ↔ {b} <span>×</span></button>)}</div>
     <div className="jumper-tray">
      {Object.entries(info.board.jumpers).map(([name,j])=><label key={name}><span>{name}</span>
       <select aria-label={`${name} position`} value={state.jumpers[name]} onChange={e=>{void physical({action:'jumper',name,value:e.target.value});}}>
        {j.states.map(s=><option key={s} value={s}>{s==='open'?'Open':s==='closed'?'Closed':`Pins ${s}`}</option>)}
       </select></label>)}
     </div>
    </div>
    {state.warnings.length>0&&<div className="warning" role="status">{state.warnings.map(w=><p key={w}>{w}</p>)}</div>}
    {diagnostics}
    </aside>
    </div>
   </section>}
   {screen==='ide'&&<section className="ide-panel panel" aria-label="IDE">
    <div className="panel-heading"><h2>IDE</h2><span className="current-exercise">{spec?.title}</span></div>
    <div className="editor-toolbar"><span>program.c</span><span>{firmwareKind==='hex'?'HEX firmware loaded':dirty?'C source · compile pending':'C source · compiled'}</span></div>
    <div className="code-editor-shell">
     <div className="line-number-gutter" aria-hidden="true"><pre ref={lineNumbers}>{Array.from({length:source.split('\n').length},(_,i)=>i+1).join('\n')}</pre></div>
     <div className="code-input">
     <pre ref={sourceHighlight} className="code-highlight" aria-hidden="true"><CSource source={source}/><br/></pre>
     <textarea ref={attachSourceEditor} aria-label="Embedded C editor" className="code-editor" value={source} spellCheck={false} disabled={busy} wrap="off" onScroll={syncEditorScroll}
      onChange={e=>{latestSource.current=e.target.value;setSource(e.target.value);setDirty(true);setFirmwareKind('c');}}
      onKeyDown={e=>{
       if(e.key!=='Tab'&&e.key!=='Enter'&&e.key!=='Backspace')return;
       if(e.nativeEvent.isComposing||(e.key!=='Tab'&&(e.ctrlKey||e.altKey||e.metaKey)))return;
       const editor=e.currentTarget,start=editor.selectionStart,end=editor.selectionEnd;
       let remove=0;
       if(e.key==='Backspace'){
        if(start!==end)return;
        const prefix=source.slice(source.slice(0,start).lastIndexOf('\n')+1,start);
        if(!/^[ \t]*$/.test(prefix))return;
        const spaces=prefix.match(/ +$/)?.[0].length??0;
        // Each literal tab ends at a tab stop, so only trailing spaces count.
        remove=spaces>0?(spaces-1)%4+1:0;
        if(remove<=1)return;
       }
       e.preventDefault();
       if(e.key==='Tab'&&e.shiftKey){
        const first=source.slice(0,start).lastIndexOf('\n')+1;
        const lineEnd=source.indexOf('\n',end>start?end-1:end);
        const last=lineEnd<0?source.length:lineEnd;
        let removedBeforeStart=0,removedBeforeEnd=0;
        const block=source.slice(first,last).replace(/^(?:\t| {1,4})/gm,(indent,offset:number)=>{
         removedBeforeStart+=Math.min(indent.length,Math.max(0,start-first-offset));
         removedBeforeEnd+=Math.min(indent.length,Math.max(0,end-first-offset));
         return '';
        });
        const next=source.slice(0,first)+block+source.slice(last);
        if(next===source)return;
        pendingEditorSelection.current={start:start-removedBeforeStart,end:end-removedBeforeEnd,direction:editor.selectionDirection};
        latestSource.current=next;setSource(next);setDirty(true);setFirmwareKind('c');
        return;
       }
       const lineStart=source.slice(0,start).lastIndexOf('\n')+1;
       const insertion=e.key==='Enter'?'\n'+source.slice(lineStart,start).match(/^[ \t]*/)![0]:e.key==='Tab'?'    ':'';
       const next=source.slice(0,start-remove)+insertion+source.slice(end),position=start-remove+insertion.length;
       latestSource.current=next;
       // Restore the caret during the commit, before another key can be typed.
       if(next===source)editor.setSelectionRange(position,position);
       else {pendingEditorSelection.current={start:position,end:position,direction:'none'};setSource(next);}
       setDirty(true);setFirmwareKind('c');
      }}/>
     </div>
    </div>
    <div className="ide-actions">
     <div className="file-actions"><button onClick={()=>fileInput.current?.click()} disabled={busy}>↑ Open C / HEX</button><button onClick={()=>download(source,'program.c')}>↓ C</button><button disabled={!hex} onClick={()=>hex&&download(hex,'firmware.hex')}>↓ HEX</button>
      <input ref={fileInput} type="file" accept=".c,.hex" hidden disabled={busy} aria-label="Upload C or HEX" onChange={e=>{const f=e.target.files?.[0];if(f)void upload(f);e.target.value='';}}/></div>
     <button className="compile" disabled={busy||!info.compiler.available} onClick={()=>{void compile();}}>{busy?(loadingHex?'Loading HEX…':'Compiling…'):'Compile C'}</button>
     {runtimeControls}
    </div>
    {diagnostics}
    <DebugPanel loaded={state.loaded} status={state.status}/>
   </section>}
   {screen==='bench'&&<Suspense fallback={<p className="loading">Loading 3D workbench…</p>}><Workbench info={info} layout={layout} state={state} publish={publishState} compileSource={code=>compile(code)}
    control={action=>{void control(action);}} runtimeControls={runtimeControls}/></Suspense>}
   {screen==='labs'&&<section className="labs-panel" aria-label="Lab exercises">
    <div className="panel-heading"><h2>Lab exercises</h2></div>
    {spec&&<ExerciseSolution exercise={spec} compiling={busy} onOpen={openSolution} onDownload={download}/>}
    {[6,7,8,9,10,11].map(lab=><section className="lab-group" key={lab} aria-labelledby={`lab-${lab}`}>
     <h3 id={`lab-${lab}`}>Lab {lab}{lab===11?' · PWM':''}</h3>
     <div className="exercise-grid">{info.exercises.filter(e=>e.lab===lab).map(e=><button key={e.id} className="exercise-card" aria-pressed={exercise===e.id} onClick={()=>setExercise(e.id)}>{e.title}</button>)}</div>
    </section>)}
    {error&&<p role="alert" className="error">{error}</p>}
   </section>}
  </main>
  <footer className="app-footer">
   <span>LPC1768 Virtual Lab</span>
   <a href="https://github.com/h4rshupadhyay/LPC1768_simulator" target="_blank" rel="noopener noreferrer" title="View source on GitHub (opens in a new tab)">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M6 3v12a4 4 0 0 0 4 4h8M6 7h8a4 4 0 0 1 4 4v8"/><circle cx="6" cy="3" r="2"/><circle cx="18" cy="5" r="2"/><circle cx="18" cy="19" r="2"/><path d="M18 7v4"/></svg>
    <span>View on GitHub</span>
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M7 17 17 7M7 7h10v10"/></svg>
   </a>
  </footer>
 </div>;
}
