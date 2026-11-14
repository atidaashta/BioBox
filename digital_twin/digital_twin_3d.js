'use strict';

function showTwin(data) {
 const record = data.latest;
 const leaves = record?.leaves || [], count = leaves.length, topView = record?.view === 'top';
 const rate = Number.isFinite(data.rate) ? data.rate / 100 : .02;
 const canvas = document.getElementById('plant');
 const slider = document.getElementById('days');
 const dayText = document.getElementById('day-text');
 const countText = document.getElementById('count-text');
 const countBadge = document.getElementById('count-badge');
 const toggle = document.getElementById('leaves-button');
 const list = document.getElementById('leaf-list');
 const tray = document.getElementById('leaf-tray');
 const empty = document.getElementById('twin-empty');
 const date = record?.captured_at;
 if (date && Number.isFinite(Date.parse(date))) {
  const time = document.getElementById('capture-time');
  time.dateTime = date;
  time.textContent = new Intl.DateTimeFormat('en-GB', {
   dateStyle: 'medium', timeStyle: 'short', timeZone: 'Europe/Berlin'
  }).format(new Date(date));
  time.hidden = false;
 }
 empty.hidden = Boolean(count);
 if (!count) {
  empty.textContent = 'No usable leaf contours';
  return;
 }
 countBadge.textContent = (record.count_estimated ? '≈' : '') + count;
 if (record.count_estimated) toggle.title = 'Leaf count estimated automatically';
 toggle.hidden = false;
 canvas.hidden = false;
 slider.disabled = false;

 const el=(tag,attrs={},...children)=>{
  const e=document.createElement(tag);
  for(const [key,val] of Object.entries(attrs))e.setAttribute(key,val);
  e.append(...children);return e;
 };
 const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
 const mix=(a,b,t)=>a+(b-a)*t;
 const sub=(a,b)=>[a[0]-b[0],a[1]-b[1],a[2]-b[2]];
 const dot=(a,b)=>a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
 const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
 const unit=a=>{const d=Math.hypot(...a)||1;return [a[0]/d,a[1]/d,a[2]/d];};
 const tau=Math.PI*2,light=unit([-.62,.76,-.46]);
 const css=c=>'rgb('+c.map(v=>Math.round(clamp(v,0,255))).join(',')+')';
 const lift=(color,n)=>color.map((v,i)=>v*n+(i===1?1.6:1));
 const seed=(a,b)=>{const v=Math.sin(a*125.1+b*63.9)*43758.5453;return v-Math.floor(v);};
 function surface(faces,points,color,options={}){
  const {twoSided=false,gloss=0,line=false,width=.6,opacity=1}=options;
  let shade=1, shine=0;
  if(!line){
   let normal=cross(sub(points[1],points[0]),sub(points[2],points[0]));
   if(Math.hypot(...normal)<1e-10&&points.length===4)normal=cross(sub(points[2],points[0]),sub(points[3],points[0]));
   normal=unit(normal);
   const l=dot(normal,light), diff=twoSided?Math.abs(l):Math.max(0,l);
   shade=.69+.29*diff;
   shine=gloss*Math.pow(diff,6);
  }
  const colorCss=css(color.map((v,i)=>v*shade+shine*(i===1?1:.8)));
  faces.push({points,color:colorCss,line,width,opacity});
 }
 function tube(faces,a,b,ra,rb,color,sides=6){
  const dir=unit(sub(b,a));
  if(Math.hypot(...dir)<.01)return;
  const u=unit(cross(dir,Math.abs(dir[1])>.85?[1,0,0]:[0,1,0])),v=cross(dir,u);
  const p=(c,r,k)=>{const t=k*tau/sides;return c.map((x,i)=>x+r*(u[i]*Math.cos(t)+v[i]*Math.sin(t)));};
  for(let k=0;k<sides;k++)surface(faces,[p(a,ra,k+1),p(b,rb,k+1),p(b,rb,k),p(a,ra,k)],color);
 }
 function pot(faces,r,h){
  const dark=[60,62,56],rim=[70,72,63],soil=[76,58,42];
  const n=48;
  const rings=[[-h,.77,dark],[-h+.025,.80,dark],[-h*.20,.96,dark],[-h*.18,.97,[46,48,43]],[-h*.16,1.012,rim],
   [-.026,1.022,rim],[.013,1.003,rim],[.021,.982,rim],[.021,.947,rim],[-.035,.929,[46,46,39]],[-.058,.925,[48,43,35]]];
  const p=(a,y,k)=>[r*a*Math.cos(k*tau/n),y,r*a*Math.sin(k*tau/n)];
  for(let k=0;k<n;k++){
   for(let i=1;i<rings.length;i++){
    const [y0,r0]=rings[i-1],[y1,r1,color]=rings[i];
    surface(faces,[p(r0,y0,k),p(r1,y1,k),p(r1,y1,k+1),p(r0,y0,k+1)],color,{gloss:i>=5?12:5});
   }
   const pebble=seed(k,17);
   surface(faces,[[0,-.056,0],p(.927,-.058,k+1),p(.927,-.058,k)],soil);
   for(let j=0;j<2;j++){
    const angle=k*tau/n+seed(k,j)*tau/n, rr=Math.sqrt(seed(k,j+9))*.87*r;
    const x=Math.cos(angle)*rr,z=Math.sin(angle)*rr,y=-.054+pebble*.002,sz=r*(.008+seed(k,j+7)*.021);
    surface(faces,[[x-sz,y,z],[x,y+.003,z+sz*.75],[x+sz*.7,y,z-sz*.7]],lift(soil,.74+seed(k,j+13)*.72),{twoSided:true});
   }
  }
 }
 function samples(s,u){
  const j=u*(s.profile.length-1),i=Math.floor(j),a=s.profile[i],b=s.profile[Math.min(i+1,s.profile.length-1)];
  const lo=mix(a[0],b[0],j-i),hi=mix(a[1],b[1],j-i);
  const chord=mix((s.profile[0][0]+s.profile[0][1])*.5,(s.profile.at(-1)[0]+s.profile.at(-1)[1])*.5,u);
  return [lo,mix((lo+hi)*.5,clamp(chord,lo,hi),.30),hi];
 }
 function blade(s,plane){
  const [cx,cy]=s.center,[ax,ay]=s.axis;
  return (u,v)=>{
   const [lo,mid,hi]=samples(s,u);
   const side=v<0?mix(mid,lo,-v):mix(mid,hi,v);
   const t=(u-.5)*s.length;
   return plane(cx+ax*t-ay*side,cy+ay*t+ax*side,u,v,hi-lo);
  };
 }
 function leafMaterial(s){
  // Take the hue from the visible blade. Simulated light adds shape, without repainting discoloured leaves green.
  const [r,g,b]=s.rgb;
  return [clamp(.90*r+7,21,224),clamp(1.04*g+11,38,235),clamp(.86*b+7,17,212)];
 }
 function leafFaces(faces,s,at,veins=true){
  const color=leafMaterial(s),rows=s.profile.length-1,cols=count>85?4:6;
  const grid=Array.from({length:rows+1},(_,j)=>Array.from({length:cols+1},(_,k)=>at(j/rows,2*k/cols-1)));
  for(let j=0;j<rows;j++)for(let k=0;k<cols;k++){
   const t=(j+.5)/rows,edge=Math.abs((k+.5)/cols*2-1),jitter=seed(j+13*s.center[0],k+17*s.center[1])-.5;
   const rgb=lift(color,.94+.11*Math.sin(Math.PI*t)-.07*edge+.045*jitter+(k<cols/2?.05:0));
   surface(faces,[grid[j][k],grid[j+1][k],grid[j+1][k+1],grid[j][k+1]],rgb,{twoSided:true,gloss:14});
  }
  if(!veins)return;
  const vein=css(color.map((v,i)=>mix(v,i===0?190:i===1?206:124,.46)));
  const rib=(path,width,opacity)=>faces.push({points:path,color:vein,line:true,width,opacity});
  for(let j=0;j<rows;j++)rib([at(j/rows,0),at((j+1)/rows,0)],.60,.77-.40*j/rows);
  for(let j=0;j<6;j++)for(const sign of [-1,1]){
   const u=.15+j*.12, tip=Math.min(.974,u+.18-j*.01), edge=.82+seed(j,sign)*.13;
   const path=[at(u,0),at(mix(u,tip,.4),sign*.38),at(mix(u,tip,.72),sign*.70),at(tip,sign*edge)];
   for(let i=1;i<path.length;i++)rib([path[i-1],path[i]],.42,.46);
  }
 }
 function cameraPaint(ctx,faces,project){
  const drawn=faces.map(f=>{
   const q=f.points.map(project);
   return {f,q,d:q.reduce((sum,p)=>sum+p[2],0)/q.length-(f.line?.0025:0)};
  }).sort((a,b)=>b.d-a.d);
  ctx.lineJoin='round';ctx.lineCap='round';
  for(const {f,q} of drawn){
   ctx.globalAlpha=f.opacity;ctx.beginPath();ctx.moveTo(q[0][0],q[0][1]);
   for(let i=1;i<q.length;i++)ctx.lineTo(q[i][0],q[i][1]);
   if(f.line){ctx.strokeStyle=f.color;ctx.lineWidth=f.width;ctx.stroke();}
   else{
    ctx.closePath();ctx.fillStyle=f.color;ctx.fill();
    // Cover antialiasing seams between adjacent facets.
    ctx.strokeStyle=f.color;ctx.lineWidth=.42;ctx.stroke();
   }
  }
  ctx.globalAlpha=1;
 }
 const outlines=leaves.flatMap(s=>{
  const at=blade(s,(x,y)=>[x,y]);
  return s.profile.flatMap((_,i)=>[at(i/(s.profile.length-1),-1),at(i/(s.profile.length-1),1)]);
 });
 const xs=outlines.map(p=>p[0]),ys=outlines.map(p=>p[1]);
 const xlo=count?Math.min(...xs):-.5,xhi=count?Math.max(...xs):.5;
 const ylo=count?Math.min(...ys):-.5,yhi=count?Math.max(...ys):.5;
 const xmid=(xlo+xhi)*.5,ymid=(ylo+yhi)*.5;
 const scale=2.65/Math.max(.1,xhi-xlo,yhi-ylo),spread=Math.max(.5,(xhi-xlo)*scale);
 const canopyHeight=topView?1.78:Math.max(.48,(yhi-ylo)*scale+.08);
 const potR=clamp(spread*.379,.38,1.03),potH=clamp(.35*canopyHeight,.48,1.08);
 const ordered=[...leaves].sort((a,b)=>a.center[0]-b.center[0]);
 function stemAt(stem,y){
  const t=clamp(y/stem.top,0,1),ease=t*(1.18-.18*t);
  return [mix(stem.x0,stem.x1,ease)+Math.sin(t*Math.PI)*stem.lean,y,mix(stem.z0,stem.z1,ease)];
 }
 function grow(factor){
  const faces=[], height=canopyHeight*Math.pow(factor,.63);
  pot(faces,potR,potH);
  const stems=[],n=Math.min(12,Math.max(1,Math.round(Math.sqrt(count)*1.14)));
  for(let i=0;i<n;i++){
   const b=ordered[Math.min(count-1,Math.floor((i+.5)*count/n))];
   const ax=(b.center[0]-xmid)*scale,depth=seed(i,2)-.5;
   const stem={x0:ax*.48,x1:ax*.95*factor,z0:depth*potR*.91,z1:depth*potR*2.05*factor,
    lean:(seed(i,8)-.5)*.19,top:height,max:0};
   stems.push(stem);
  }
  for(const s of leaves){
   const mapXY=(x,y)=>[(x-xmid)*scale*factor,topView?(y-ymid)*scale*factor:(yhi-y)*scale*Math.pow(factor,.63)+.055];
   const base=blade(s,mapXY)(0,0),c=s.center;
   const r=seed(c[0],c[1]),rnd=seed(c[1],c[0]);
   const nodeY=topView?height*(.36+.61*r):Math.max(.035,base[1]-.028-s.length*scale*.12);
   let chosen=stems[0],dist=Infinity;
   for(const stem of stems){
    const p=stemAt(stem,nodeY),d=Math.abs(p[0]-base[0])+(topView?.42*Math.abs(p[2]-base[1]):0);
    if(d<dist){dist=d;chosen=stem;}
   }
   chosen.max=Math.max(chosen.max,nodeY);
   const node=stemAt(chosen,nodeY);
   const fold=(.18+.23*r)*(rnd<.45?-1:1);
   const at=blade(s,(x,y,u,v,w)=>{
    const [X,Y]=mapXY(x,y),arc=Math.sin(Math.PI*u);
    const bend=scale*factor*(s.length*(.14*arc-.12*u*u)+w*(.16*(1-v*v)*arc+fold*v));
    return topView?[X,nodeY+.038+bend,Y]:[X,Y,node[2]+(rnd-.5)*potR*.81+bend+(u-.5)*s.length*scale*fold];
   });
   const root=at(0,0);
   const elbow=node.map((v,i)=>mix(v,root[i],.61)+(i===1?.021:0));
   const stalk=clamp(s.length*scale*.028,.003,.013);
   tube(faces,node,elbow,stalk,stalk*.80,[101,133,68]);
   tube(faces,elbow,root,stalk*.80,stalk*.56,[104,137,70]);
   leafFaces(faces,s,at,s.length*scale>.035);
  }
  for(const stem of stems){
   let last=stemAt(stem,-.052);
   const end=stem.max+.024;
   for(let j=1;j<=9;j++){
    const t=j/9,p=stemAt(stem,end*t),r=.0165*(1-.74*t);
    tube(faces,last,p,r+.0014,r,[92,119,61],7);last=p;
   }
  }
  return {faces,height};
 }
 const homeYaw=topView?-.26:-.12,homePitch=topView?.86:.17;
 let yaw=homeYaw,pitch=homePitch,drag=null,scene=null,queued=false,requestedSize=1,drawnSize=0;
 function render(){
  if(canvas.hidden)return;
  const {width:w,height:h}=canvas.getBoundingClientRect(),dpr=Math.min(window.devicePixelRatio||1,2);
  if(!w||!h)return;
  if(drawnSize!==requestedSize){scene=grow(requestedSize);drawnSize=requestedSize;}
  const cw=Math.round(w*dpr),ch=Math.round(h*dpr);
  if(canvas.width!==cw||canvas.height!==ch){canvas.width=cw;canvas.height=ch;}
  const ctx=canvas.getContext('2d');
  if(!ctx)return;
  ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);
  const focal=Math.min((w-24)/Math.max(2.8,spread*1.19),(h-20)/Math.max(2.78,(canopyHeight+potH)*1.20));
  const targetY=(scene.height-potH)*.47;
  const c=Math.cos(yaw),s=Math.sin(yaw),cp=Math.cos(pitch),sp=Math.sin(pitch);
  const project=p=>{
   const x=p[0]*c+p[2]*s,z=-p[0]*s+p[2]*c,y=p[1]-targetY;
   const ry=y*cp+z*sp,rz=-y*sp+z*cp,f=7.5/(7.5+rz)*focal;
   return [w/2+x*f,h*.51-ry*f,rz];
  };
  const floor=project([0,-potH-.025,0]),rw=potR*focal*.93,rh=rw*(.16+.46*Math.abs(sp));
  ctx.save();ctx.translate(floor[0],floor[1]+2);ctx.scale(rw,rh);
  const shadow=ctx.createRadialGradient(.12,.04,.1,.12,.04,1.22);
  shadow.addColorStop(0,'rgba(38,54,41,.30)');shadow.addColorStop(.49,'rgba(51,70,56,.20)');shadow.addColorStop(1,'rgba(51,70,56,0)');
  ctx.fillStyle=shadow;ctx.fillRect(-1.15,-1.22,2.5,2.44);ctx.restore();
  cameraPaint(ctx,scene.faces,project);
 }
 function requestRender(){
  if(!queued){queued=true;requestAnimationFrame(()=>{queued=false;render();});}
 }
 function update(){
  const days=Number(slider.value);
  dayText.textContent = days ? `Scenario · +${days} ${days === 1 ? 'day' : 'days'}` : 'At capture';
  if(!count)return;
  requestedSize=clamp(Math.pow(1+rate,days*.5),.44,1.53);
  requestRender();
 }
 function drawTiles(){
  for(const [i,s] of leaves.entries()){
   const tile=el('canvas',{width:'132',height:'84','aria-hidden':'true'});
   const item=el('li',{'aria-label':'Leaf '+(i+1)},tile,el('span',{'aria-hidden':'true'},String(i+1)));
   list.append(item);
   const ctx=tile.getContext('2d');if(!ctx)continue;
   const [ax,ay]=s.axis,faces=[];
   const at=blade(s,(x,y,u,v,w)=>{
    const dx=x-s.center[0],dy=y-s.center[1];
    return [dx*ax+dy*ay,dy*ax-dx*ay,-w*(1-v*v)*.16+Math.sin(Math.PI*u)*s.length*.14];
   });
   const sizeX=Math.max(.0001,s.length),sizeY=Math.max(.0001,...s.profile.map(a=>a[1]-a[0]));
   const f=Math.min(94/sizeX,53/sizeY)*clamp(.78+Math.sqrt(s.length)*.44,.78,1.0);
   leafFaces(faces,s,at);
   cameraPaint(ctx,faces,p=>[66+(p[0]*.96-p[1]*.27)*f,42+(p[0]*.27+p[1]*.96)*f,p[2]]);
  }
 }
 function toggleTray(){
  const show=tray.hidden;
  if(show&&!list.childElementCount)drawTiles();
  tray.hidden=!show;canvas.hidden=show;
  toggle.setAttribute('aria-pressed',String(show));
  countText.textContent=show?'Back to plant':'Count leaves';
  if(!show)requestRender();
 }
 toggle.addEventListener('click',toggleTray);
 slider.addEventListener('input',update);
 canvas.addEventListener('pointerdown',e=>{
  if(e.button!==0)return;
  drag={id:e.pointerId,x:e.clientX,y:e.clientY};canvas.setPointerCapture(e.pointerId);
 });
 canvas.addEventListener('pointermove',e=>{
  if(drag?.id!==e.pointerId)return;
  yaw+=(e.clientX-drag.x)*.011;pitch=clamp(pitch+(e.clientY-drag.y)*.010,-.48,1.34);
  drag.x=e.clientX;drag.y=e.clientY;requestRender();
 });
 for(const type of ['pointerup','pointercancel','lostpointercapture'])canvas.addEventListener(type,()=>{drag=null;});
 canvas.addEventListener('dblclick',()=>{yaw=homeYaw;pitch=homePitch;requestRender();});
 canvas.addEventListener('keydown',e=>{
  if(e.key==='ArrowLeft')yaw-=.13;
  else if(e.key==='ArrowRight')yaw+=.13;
  else if(e.key==='ArrowUp')pitch=clamp(pitch+.08,-.48,1.34);
  else if(e.key==='ArrowDown')pitch=clamp(pitch-.08,-.48,1.34);
  else if(e.key==='Home'){yaw=homeYaw;pitch=homePitch;}
  else return;
  e.preventDefault();requestRender();
 });
 new ResizeObserver(requestRender).observe(canvas);
 update();
}

// The same source files work from localhost and when opened directly.
(() => {
 const loader = document.getElementById('data-load');
 const input = document.getElementById('data-file');
 const status = document.getElementById('twin-empty');
 const pair = value => Array.isArray(value) && value.length === 2 && value.every(Number.isFinite);
 function validLeaf(leaf) {
  return leaf && pair(leaf.center) && pair(leaf.axis) &&
   Number.isFinite(leaf.length) && leaf.length > 0 &&
   Array.isArray(leaf.rgb) && leaf.rgb.length === 3 && leaf.rgb.every(Number.isFinite) &&
   Array.isArray(leaf.profile) && leaf.profile.length === 15 && leaf.profile.every(pair);
 }
 function show(data) {
  const viewer = data?.viewer;
  const leaves = viewer?.latest?.leaves;
  if (!viewer || (viewer.latest !== null &&
      (!Array.isArray(leaves) || leaves.length > 200 || !leaves.every(validLeaf)))) {
   throw new Error('Run python -B computer_vision_pipeline.py images and use the updated digital_twin.json.');
  }
  showTwin(viewer);
  loader.hidden = true;
 }
 function askForFile(message) {
  status.textContent = message;
  loader.hidden = false;
 }
 input.addEventListener('change', async () => {
  const file = input.files[0];
  if (!file) return;
  try {
   show(JSON.parse(await file.text()));
  } catch (error) {
   askForFile(error instanceof SyntaxError ? 'The JSON file could not be read.' : error.message);
   input.value = '';
  }
 });
 if (location.protocol === 'file:') {
  askForFile('Run python -B digital_twin.py to load the data automatically, or choose digital_twin.json.');
  return;
 }
 (async () => {
  try {
   const response = await fetch('digital_twin.json', {cache: 'no-store'});
   if (!response.ok) throw new Error('No 3D data found. Run the analysis first.');
   show(await response.json());
  } catch (error) {
   askForFile(error instanceof SyntaxError ? 'The JSON file could not be read.' : error.message);
  }
 })();
})();
