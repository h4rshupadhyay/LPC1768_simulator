// Each browser tab gets its own simulator on a public host; the local server ignores this.
const SESSION_KEY='lpc-session';
let memorySession='';

function newSessionId(){
 const bytes=new Uint8Array(18);
 crypto.getRandomValues(bytes);
 return Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
}

export function sessionId(){
 try {
  let id=sessionStorage.getItem(SESSION_KEY);
  if(!id){id=newSessionId();sessionStorage.setItem(SESSION_KEY,id);}
  return id;
 } catch {
  return memorySession||=newSessionId();
 }
}

const LOCAL=['localhost','127.0.0.1','[::1]'].includes(location.hostname);

export async function api<T>(path:string,data?:unknown):Promise<T> {
 const headers:Record<string,string>={'X-LPC-Session':sessionId()};
 const res=await fetch(path,data===undefined?{headers}:{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify(data)});
 const text=await res.text();
 let value;
 try {value=JSON.parse(text);} catch {
  throw new Error(LOCAL?`Local server returned ${res.status}. Start the Python backend.`
   :`Simulator server returned ${res.status}. It may be waking up; reload in a minute.`);
 }
 if(!res.ok) throw new Error(value.error||`Request failed (${res.status})`);
 return value as T;
}
