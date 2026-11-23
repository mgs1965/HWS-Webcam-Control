(function(){
try{history.scrollRestoration='manual'}catch(e){}addEventListener('load',()=>{if(!location.hash)scrollTo(0,0)});
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
HWS.rainfallMonths=function(rows,year){return Array.from({length:12},(_,i)=>{const month=year+'-'+String(i+1).padStart(2,'0'),data=rows.filter(r=>r.d.startsWith(month)&&has(r.v));return [new Date(2000,i,1).toLocaleDateString('en-GB',{month:'short'}),data.length?data.reduce((sum,r)=>sum+Number(r.v),0):null]})};
HWS.date=function(value){const s=String(value||''),iso=/^\d{8}$/.test(s)?s.slice(0,4)+'-'+s.slice(4,6)+'-'+s.slice(6,8):s,d=new Date(/^\d{4}-\d{2}-\d{2}$/.test(iso)?iso+'T12:00:00':iso);return Number.isFinite(d.getTime())?d.toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'}):'Date unavailable'};
HWS.stationDate=function(){const parts=new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/London',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date()),part=k=>parts.find(p=>p.type===k).value;return part('year')+'-'+part('month')+'-'+part('day')};
HWS.weatherStatus=function(weather,error){const t=Date.parse(weather.updated||''),age=Number.isFinite(t)?Math.max(0,Math.floor((Date.now()-t)/60000)):null,last=age===null?'No weather reading available.':'Last reading: '+new Date(t).toLocaleString('en-GB')+' ('+age+' min ago).';return {last,warning:error?last+' Weather refresh failed; the connection or station may be unavailable.':age===null?'No weather data available. The station may be offline.':age>=10?last+' Weather data is stale; the station may be offline.':'',fresh:age!==null&&age<10}};
HWS.refreshWeather=async function(current){
 async function read(url){const r=await fetch(url+'?ts='+Date.now(),{cache:'no-store'});if(!r.ok)throw new Error(url+': HTTP '+r.status);return r.json()}
 let next,error;
 try{next=await read('weather-live.json');if(!next||!Number.isFinite(Date.parse(next.updated)))throw new Error('Live weather has no valid timestamp')}
 catch(e){error=e;next=null}
 if(!next||Date.now()-Date.parse(next.updated)>120000){
  try{const data=await read('dashboard-data.json'),w=data.weather;if(!w||!Number.isFinite(Date.parse(w.updated)))throw new Error('Dashboard weather has no valid timestamp');if(!next||Date.parse(w.updated)>Date.parse(next.updated))next=w}
  catch(e){if(!next)throw new Error('Weather data unavailable. Check the weather station connection and service. ('+(error?error.message+'; ':'')+e.message+')')}
 }
 return Date.parse(next.updated)>=Date.parse(current.updated||'')||!Number.isFinite(Date.parse(current.updated))?next:current;
};
HWS.chart=function(box,o){const S=(o.series||[]).filter(s=>s.pts&&s.pts.length),esc=t=>String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;');
 if(!S.length){box.insertAdjacentHTML('beforeend','<p class="muted">No data yet</p>');return}
 const w=o.w||700,h=o.h||190,L=o.L||50,R=8,T=8,B=22,pw=w-L-R,ph=h-T-B,ys=S.flatMap(s=>s.pts.map(p=>p[1])),cats=o.cats,n=cats?cats.length:0;
 let lo=o.bars||o.zero?Math.min(0,...ys):Math.min(...ys),hi=Math.max(...ys);if(hi===lo){hi+=1;if(!o.bars&&!o.zero)lo-=1}
 const xs=S.flatMap(s=>s.pts.map(p=>p[0])),x0=Math.min(...xs),x1=Math.max(...xs),X=x=>cats?L+(x+.5)/n*pw:L+(x-x0)/((x1-x0)||1)*pw,Y=v=>T+ph-(v-lo)/(hi-lo)*ph,dg=o.dig||0,yd=hi-lo<5?Math.max(dg,1):dg;
 let g='<svg viewBox="0 0 '+w+' '+h+'" style="width:100%;height:auto;font-size:'+(o.fs||11)+'px" fill="#a9bdce">';
 for(let i=0;i<4;i++){const v=lo+(hi-lo)*i/3,y=Y(v).toFixed(1);g+='<line x1="'+L+'" x2="'+(w-R)+'" y1="'+y+'" y2="'+y+'" stroke="#2a4960" stroke-width=".6"/><text x="'+(L-4)+'" y="'+(+y+4)+'" text-anchor="end">'+HWS.fmt(v,yd,o.unit)+'</text>'}
 if(cats){const step=Math.ceil(n/8);cats.forEach((c,i)=>{if(i%step===0)g+='<text x="'+X(i).toFixed(1)+'" y="'+(h-6)+'" text-anchor="middle">'+esc(c)+'</text>'})}
 else for(let i=0;i<5;i++){const x=x0+(x1-x0)*i/4;g+='<text x="'+X(x).toFixed(1)+'" y="'+(h-6)+'" text-anchor="'+(i===0?'start':i===4?'end':'middle')+'">'+esc(o.xfmt?o.xfmt(x):Math.round(x))+'</text>'}
 for(const s of S){if(o.bars){const bw=Math.max(pw/n-2,1);for(const p of s.pts){const y=Y(p[1]),y0=Y(Math.max(lo,0));g+='<rect x="'+(X(p[0])-bw/2).toFixed(1)+'" y="'+Math.min(y,y0).toFixed(1)+'" width="'+bw.toFixed(1)+'" height="'+Math.max(Math.abs(y0-y),p[1]>0?1:0).toFixed(1)+'" fill="'+s.color+'"><title>'+esc((cats?cats[p[0]]:p[0])+': '+HWS.fmt(p[1],yd,o.unit))+'</title></rect>'}}
  else g+='<polyline fill="none" stroke="'+s.color+'" stroke-width="2" stroke-linejoin="round" points="'+s.pts.map(p=>X(p[0]).toFixed(1)+','+Y(p[1]).toFixed(1)).join(' ')+'"/>'}
 box.insertAdjacentHTML('beforeend',g+'</svg><p class="muted" style="margin:4px 0 0;font-size:12px">'+S.map(s=>'<span style="color:'+s.color+'">&#9632;</span> '+esc(s.name)+(o.unit?' ('+esc(HWS.label(o.unit).trim())+')':'')).join(' &nbsp; ')+'</p>')};
function zoomable(v){return !!v.querySelector('polyline,rect')&&!v.closest('#hws-zoom')&&(v.viewBox.baseVal.width>=250)}

document.addEventListener('mouseover',e=>{const v=e.target.closest&&e.target.closest('svg');if(v&&zoomable(v))v.style.cursor='zoom-in'});
document.addEventListener('click',e=>{const v=e.target.closest&&e.target.closest('svg');if(!v||!zoomable(v)||v.closest('#hws-zoom'))return;const card=v.closest('section,.s-card,.card,div'),h=card&&card.querySelector('h2,h3'),o=document.createElement('div');o.id='hws-zoom';const box=document.createElement('div');box.className='zbox';if(h){const t=document.createElement('h2');t.textContent=h.textContent;box.append(t)}const c=v.cloneNode(true);c.removeAttribute('style');c.style.fontSize=(parseFloat(v.style.fontSize)||11)+'px';c.style.cursor='default';box.append(c);const n=v.nextElementSibling;if(n&&n.tagName==='P')box.append(n.cloneNode(true));o.append(box);const close=()=>{o.remove();document.removeEventListener('keydown',k)},k=ev=>{if(ev.key==='Escape')close()};o.addEventListener('click',close);document.addEventListener('keydown',k);document.body.append(o)});

function bar(){if(document.getElementById('hws-bar'))return;const b=document.createElement('div');b.id='hws-bar';
 const mk=(label,key,cur,opts)=>{const s=document.createElement('select');s.setAttribute('aria-label',label);for(const[v,t]of opts){const o=document.createElement('option');o.value=v;o.textContent=t;if(v===cur)o.selected=true;s.append(o)}s.addEventListener('change',()=>{set(key,s.value);location.reload()});b.append(s)};
 mk('Units','hws-units',units,[['uk','°C · mph'],['metric','°C · km/h'],['us','°F · inHg']]);mk('Theme','hws-theme',theme,[['green','Racing green'],['dark','Navy'],['light','Light'],['auto','Auto']]);document.body.append(b)}
if(document.body)bar();else document.addEventListener('DOMContentLoaded',bar);
})();
