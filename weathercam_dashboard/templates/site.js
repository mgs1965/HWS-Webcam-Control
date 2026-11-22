(function(){
const get=(k,d)=>{try{return localStorage.getItem(k)||d}catch(e){return d}},set=(k,v)=>{try{localStorage.setItem(k,v)}catch(e){}};
const theme=get('hws-theme','green'),units=get('hws-units','uk'),root=document.documentElement;
const resolved=theme==='auto'?(matchMedia('(prefers-color-scheme: light)').matches?'light':'dark'):theme;root.dataset.theme=resolved;
const has=v=>v!==null&&v!==undefined&&v!==''&&isFinite(Number(v));
// Each rule: unit text -> [unit system -> [factor, offset, new label, minimum digits]]
const RULES={'°C':{us:[1.8,32,'°F']},'°':{us:[1.8,32,'°']},'mph':{metric:[1.609344,0,'km/h']},'hPa':{us:[0.02953,0,'inHg',2]},'mm':{us:[0.0393701,0,'in',2]},'mm/h':{us:[0.0393701,0,'in/h',2]}};
function rule(unit){const r=RULES[String(unit||'').trim()];return r&&r[units]}
const HWS={units,theme,
 conv(v,unit,delta){const r=rule(unit);return r&&has(v)?Number(v)*r[0]+(delta?0:r[1]):v},
 label(unit){const r=rule(unit);if(!r)return unit;const lead=String(unit).match(/^\s*/)[0];return lead+r[2]},
 digits(unit,d){const r=rule(unit);return r&&r[3]?Math.max(d,r[3]):d},
 fmt(v,d,unit,delta){if(!has(v))return'–';d=d||0;unit=unit||'';return Number(HWS.conv(v,unit,delta)).toFixed(HWS.digits(unit,d))+HWS.label(unit)},
 compass(deg){const N=['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW','W','WNW','NW','NNW'];return has(deg)?N[Math.round((((Number(deg)%360)+360)%360)/22.5)%16]:'–'}};
window.HWS=HWS;
function bar(){if(document.getElementById('hws-bar'))return;const b=document.createElement('div');b.id='hws-bar';
 const mk=(label,key,cur,opts)=>{const s=document.createElement('select');s.setAttribute('aria-label',label);for(const[v,t]of opts){const o=document.createElement('option');o.value=v;o.textContent=t;if(v===cur)o.selected=true;s.append(o)}s.addEventListener('change',()=>{set(key,s.value);location.reload()});b.append(s)};
 mk('Units','hws-units',units,[['uk','°C · mph'],['metric','°C · km/h'],['us','°F · inHg']]);mk('Theme','hws-theme',theme,[['green','Racing green'],['dark','Navy'],['light','Light'],['auto','Auto']]);document.body.append(b)}
if(document.body)bar();else document.addEventListener('DOMContentLoaded',bar);
})();
