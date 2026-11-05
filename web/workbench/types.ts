export type Target='als'|'mbed'|'bare';

export interface StimulusSpec {min:number;max:number;default:number;unit:string;label:string}
export interface PartSpec {
 kind:string;name:string;category:string;aliases:string[];interfaces:string[];supply:string;
 compat:string;compatText:string;description:string;shape:string;footprint:[number,number][];
 pins:string[];defaults:Record<string,unknown>;choices:Record<string,unknown[]>;
 stimuli:Record<string,StimulusSpec>;ratings:{supply:unknown[]|null;pins:Record<string,number>};
}
export interface Placement {x:number;z:number;rot:number;free?:boolean}
export interface PartState {
 id:string;type:string;props:Record<string,unknown>;stimuli:Record<string,number>;
 placement:Partial<Placement>;mount:Record<string,string>;damaged:string|null;
 state:Record<string,any>;pins:Record<string,number|null>;
}
export interface FixAction {label:string;steps:string[];apply?:unknown[]|null}
export interface Finding {
 key:string;severity:'info'|'warning'|'stress'|'damage-risk'|'damaged';title:string;what:string;
 why:string;consequence:string;fixes:FixAction[];parts:string[];nodes:string[];
}
export interface CircuitState {parts:PartState[];wires:[string,string,string][];findings:Finding[];damageMode:string;version:number;
 probes?:Record<string,[number,number|null][]>;now?:number}
export interface TerminalState {name:string;baud:number;text:string;received:number;mismatch:boolean}
export interface EndpointInfo {endpoint:string;node:string;volts:number|null;level:number|null;function?:string;functions?:string[]}
