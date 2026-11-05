import type {PartSpec} from './types';

// Small in-house ranking: exact/prefix word hits, alias and category hits, then
// trigram similarity so that typos ("ultrasonc", "temprature") still match.
const STOP=new Set(['a','an','the','to','for','with','and','or','of','i','want','need','measure','detect','sensor','module','show','display','use','how','my','some','something','that','can']);
const INTENT:Record<string,string[]>={
 text:['lcd','oled'],screen:['oled','lcd','display'],distance:['ultrasonic','proximity','distance'],
 heat:['temperature'],hot:['temperature'],cold:['temperature'],weather:['humidity','pressure','temperature'],
 move:['motor','servo','stepper'],spin:['motor'],rotate:['servo','stepper','encoder'],light:['led','light','ldr'],
 beep:['buzzer'],sound:['buzzer','sound'],wireless:['bluetooth'],phone:['bluetooth'],serial:['uart','serial'],
 knob:['potentiometer','encoder'],button:['button','switch','keypad'],keys:['keypad'],
 shift:['level shifter'],convert:['level shifter','regulator','adc'],power:['power','battery','regulator'],
};

function words(text:string){return text.toLowerCase().split(/[^a-z0-9.+-]+/).filter(w=>w&&!STOP.has(w));}
function trigrams(word:string){const w=`  ${word} `,out=new Set<string>();for(let i=0;i<w.length-2;i++)out.add(w.slice(i,i+3));return out;}
function similarity(a:string,b:string){
 const ta=trigrams(a),tb=trigrams(b);let common=0;ta.forEach(t=>{if(tb.has(t))common++;});
 return common/Math.max(ta.size,tb.size);
}

export interface Filters {category?:string;interface?:string;compat?:string;supply?:string}

export function searchParts(parts:PartSpec[],query:string,filters:Filters={}):PartSpec[]{
 let terms=words(query);
 terms=terms.flatMap(t=>[t,...(INTENT[t]??[])]);
 const pool=parts.filter(p=>
  (!filters.category||p.category===filters.category)&&
  (!filters.interface||p.interfaces.includes(filters.interface))&&
  (!filters.compat||(filters.compat==='direct'?p.compat.startsWith('direct'):!p.compat.startsWith('direct')))&&
  (!filters.supply||p.supply.includes(filters.supply)));
 if(!terms.length)return pool;
 const scored=pool.map(p=>{
  const name=words(p.name),aliases=p.aliases.flatMap(words),meta=[...words(p.category),...p.interfaces.flatMap(words),p.kind];
  const desc=words(p.description);
  let score=0;
  for(const t of terms){
   let best=0;
   for(const w of name){if(w===t)best=Math.max(best,10);else if(w.startsWith(t)||t.startsWith(w)&&w.length>2)best=Math.max(best,7);}
   for(const w of aliases){if(w===t)best=Math.max(best,9);else if(w.startsWith(t))best=Math.max(best,6);}
   for(const w of meta)if(w===t)best=Math.max(best,5);
   if(!best)for(const w of [...name,...aliases]){const s=similarity(w,t);if(s>.45)best=Math.max(best,s*6);}
   if(!best&&desc.includes(t))best=2;
   score+=best;
  }
  return {p,score};
 }).filter(s=>s.score>0);
 scored.sort((a,b)=>b.score-a.score||a.p.name.localeCompare(b.p.name));
 return scored.map(s=>s.p);
}
