export type Pair = [string,string];
export interface Header {kind:string;purpose:string;pins:(string|null)[]}
export interface Exercise {id:string;lab:number;title:string;description:string;cables:Pair[];jumpers:Record<string,string>;status:string}
export interface Info {
 board:{model:string;headers:Record<string,Header>;jumpers:Record<string,{states:string[];purpose:string;pinCount?:2|3}>};
 compiler:{available:boolean;name:string;note:string};exercises:Exercise[];backend:string;
}
export interface State {
 status:string;loaded:boolean;firmwareName:string;diagnostics:string;error:string|null;
 leds:boolean[];lcd:string[];segments:number[];pwm:number;cables:Pair[];jumpers:Record<string,string>;
 pots:Record<string,number>;keys:number[];sw2:boolean;sw2Pin:number;ticks:number;gpioEvents:number;lcdEdges:number;
 interrupts:number;pc:string;warnings:string[];gpio:{direction:string;latch:string}[];
 wires?:[string,string][];headerPins?:Record<string,{node:string|null;level:number|null;conflict:boolean;note?:string}[]>;
 notes?:[string,string][];target?:'als'|'mbed'|'bare';timing?:string;speed?:number;floating?:string;
 circuit?:import('./workbench/types').CircuitState;terminals?:Record<string,import('./workbench/types').TerminalState>;
 mbedLeds?:boolean[];peripherals?:Record<string,unknown>;simSeconds?:number;
}
export interface Layout {
 width:number;height:number;referencePhoto:string;headers:Record<string,[number,number]>;jumpers:Record<string,[number,number]>;
 headerOrientations:Record<string,'vertical'|'horizontal'>;
 leds:[number,number][];lcd:[number,number,number,number];seven:[number,number,number,number];
 sw1:[number,number];sw2:[number,number];ld10:[number,number];
 keypad:{origin:[number,number];step:[number,number]};pots:Record<string,[number,number]>;
}
