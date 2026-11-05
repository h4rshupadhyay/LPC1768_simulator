import type {State} from './types';

// UI consumers cannot accidentally depend on a counter that this view omits.
// The full, current execution diagnostics remain available through /api/state.
export type ViewState=Pick<State,
 'status'|'loaded'|'firmwareName'|'diagnostics'|'error'|
 'leds'|'lcd'|'segments'|'pwm'|'cables'|'jumpers'|'pots'|'keys'|'sw2'|'warnings'>&
 Partial<Pick<State,'circuit'|'terminals'|'target'|'timing'|'speed'|'floating'|'notes'|'mbedLeds'>>;

// The workbench payload (parts, findings, terminals) is compared as one serialized
// value; it changes far less often than the 50 ms poll and is small.
function workbenchKey(s:ViewState){
 return JSON.stringify([s.circuit,s.terminals,s.target,s.timing,s.speed,s.floating,s.notes,s.mbedLeds]);
}

function sameArray(a:readonly unknown[],b:readonly unknown[]):boolean {
 return a.length===b.length&&a.every((value,index)=>value===b[index]);
}

function sameRecord(a:Record<string,string|number>,b:Record<string,string|number>):boolean {
 const keys=Object.keys(a);
 return keys.length===Object.keys(b).length&&keys.every(key=>Object.hasOwn(b,key)&&a[key]===b[key]);
}

export function reconcileViewState(previous:ViewState|null,next:ViewState):ViewState {
 if(previous&&
  previous.status===next.status&&previous.loaded===next.loaded&&
  previous.firmwareName===next.firmwareName&&previous.diagnostics===next.diagnostics&&previous.error===next.error&&
  previous.pwm===next.pwm&&previous.sw2===next.sw2&&
  sameArray(previous.leds,next.leds)&&sameArray(previous.lcd,next.lcd)&&
  sameArray(previous.segments,next.segments)&&sameArray(previous.keys,next.keys)&&
  sameArray(previous.warnings,next.warnings)&&
  sameRecord(previous.jumpers,next.jumpers)&&sameRecord(previous.pots,next.pots)&&
  previous.cables.length===next.cables.length&&
  previous.cables.every((pair,index)=>sameArray(pair,next.cables[index]))&&
  workbenchKey(previous)===workbenchKey(next))return previous;
 return next;
}
