// Shared camera state for the 3D bench. The orbit controls (mouse) and the on-screen
// sliders both read and write it; a small store keeps slider moves from re-rendering
// the whole scene and keeps mouse orbits from fighting the sliders.
export interface CameraView {azimuth:number;elevation:number;distance:number;x:number;z:number}
export type CameraSource='user'|'ui';
type Listener=(view:CameraView,source:CameraSource)=>void;

export const LIMITS={azimuth:[-180,180],elevation:[8,89],distance:[60,1000],x:[-360,260],z:[-260,260]} as const;

export const PRESETS:Record<string,CameraView>={
 bench:{azimuth:0,elevation:52,distance:600,x:-50,z:10},
 kit:{azimuth:0,elevation:68,distance:330,x:-156,z:0},
 top:{azimuth:0,elevation:89,distance:520,x:-90,z:0},
 front:{azimuth:0,elevation:16,distance:420,x:-90,z:0},
 parts:{azimuth:-30,elevation:50,distance:260,x:40,z:0},
};

export function clampView(v:CameraView):CameraView{
 const c=(n:number,[lo,hi]:readonly [number,number])=>Math.min(hi,Math.max(lo,n));
 let azimuth=((v.azimuth+180)%360+360)%360-180;
 return {azimuth:c(azimuth,LIMITS.azimuth),elevation:c(v.elevation,LIMITS.elevation),
  distance:c(v.distance,LIMITS.distance),x:c(v.x,LIMITS.x),z:c(v.z,LIMITS.z)};
}

export function createCameraStore(initial:CameraView){
 let view=initial;
 const listeners=new Set<Listener>();
 return {
  get:()=>view,
  set(next:CameraView,source:CameraSource){view=clampView(next);listeners.forEach(l=>l(view,source));},
  subscribe(listener:Listener){listeners.add(listener);return()=>{listeners.delete(listener);};},
 };
}
export type CameraStore=ReturnType<typeof createCameraStore>;
