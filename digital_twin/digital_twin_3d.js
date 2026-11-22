'use strict';

function showTwin(data, photographedColour = null, referencePhoto = null) {
 const record = data.latest;
 const leaves = record?.leaves || [], count = leaves.length;
 const growth = data.growth;
 const trajectory = Array.isArray(growth?.trajectory) ? growth.trajectory : [];
 const canvas = document.getElementById('plant');
 const slider = document.getElementById('days');
 const dayText = document.getElementById('day-text');
 const countText = document.getElementById('count-text');
 const countBadge = document.getElementById('count-badge');
 const toggle = document.getElementById('leaves-button');
 const reset = document.getElementById('reset-view');
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
  if(!referencePhoto){empty.textContent='No usable leaf contours for this capture.';return;}
  canvas.hidden=false;empty.hidden=true;
  canvas.setAttribute('aria-label','Recorded photo only. No reliable 3D leaf geometry.');
  dayText.textContent='At capture · photo only';slider.disabled=true;
  const drawPhoto=()=>{
   const {width:w,height:h}=canvas.getBoundingClientRect();if(!w||!h)return;
   const dpr=Math.min(window.devicePixelRatio||1,2);
   canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);
   const ctx=canvas.getContext('2d');if(!ctx)return;
   ctx.setTransform(dpr,0,0,dpr,0,0);
   const scale=Math.min((w-20)/referencePhoto.width,(h-20)/referencePhoto.height);
   const iw=referencePhoto.width*scale,ih=referencePhoto.height*scale;
   ctx.drawImage(referencePhoto,(w-iw)/2,(h-ih)/2,iw,ih);
  };
  new ResizeObserver(drawPhoto).observe(canvas);drawPhoto();return;
 }
 countBadge.textContent = (record.count_estimated ? '≈' : '') + count;
 if (record.count_estimated) toggle.title = 'Leaf count estimated automatically';
 reset.hidden = false;
 toggle.hidden = false;
 canvas.hidden = false;
 slider.max = String(growth?.max_days || 0);
 slider.value = '0';
 slider.step = '1';
 slider.disabled = trajectory.length < 2;
 slider.title = slider.disabled ? 'More comparable photos are needed for a growth projection.' :
  `Estimated from ${growth.points} photos across ${growth.span_days} days.`;
 if (slider.disabled) dayText.textContent = 'At capture · more history needed';

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
 const canopy=record.canopy, sourceLong=Math.max(canopy?.width_px||0,canopy?.height_px||0);
 const patches=new Map();

 // Keep the holes and detached fragments of each measured leaf.
 function cutout(s){
  if(!sourceLong||!canopy.units||!Array.isArray(s.rings_q))return null;
  const rings=s.rings_q.filter(r=>Array.isArray(r)&&r.length>=6&&r.length%2===0);
  if(!rings.length)return null;
  let x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity;
  for(const r of rings)for(let i=0;i<r.length;i+=2){
   const x=r[i]/canopy.units,y=r[i+1]/canopy.units;
   if(!Number.isFinite(x)||!Number.isFinite(y)||Math.abs(x)>.52||Math.abs(y)>.52)return null;
   x0=Math.min(x0,x);y0=Math.min(y0,y);x1=Math.max(x1,x);y1=Math.max(y1,y);
  }
  if(x1<=x0||y1<=y0)return null;
  const res=Math.min(1536,sourceLong),left=Math.floor(x0*res)-2,top=Math.floor(y0*res)-2;
  const tile=document.createElement('canvas');
  tile.width=Math.ceil(x1*res)-left+2;tile.height=Math.ceil(y1*res)-top+2;
  const ctx=tile.getContext('2d');
  if(!ctx)return null;
  const px=value=>value/canopy.units*res-left,py=value=>value/canopy.units*res-top;
  ctx.beginPath();
  for(const r of rings){
   ctx.moveTo(px(r[0]),py(r[1]));
   for(let j=2;j<r.length;j+=2)ctx.lineTo(px(r[j]),py(r[j+1]));
   ctx.closePath();
  }
  ctx.fillStyle=css(s.rgb);ctx.fill('evenodd');
  ctx.lineJoin='round';ctx.strokeStyle=ctx.fillStyle;ctx.lineWidth=res/sourceLong;ctx.stroke();
  ctx.globalCompositeOperation='source-in';
  if(photographedColour){
   const w=res*canopy.width_px/sourceLong,h=res*canopy.height_px/sourceLong;
   ctx.drawImage(photographedColour,-w/2-left,-h/2-top,w,h);
  }else{
   const g=ctx.createLinearGradient(0,0,tile.width,tile.height);
   g.addColorStop(0,css(lift(s.rgb,1.06)));g.addColorStop(.48,css(s.rgb));g.addColorStop(1,css(lift(s.rgb,.89)));
   ctx.fillStyle=g;ctx.fillRect(0,0,tile.width,tile.height);
  }
  ctx.globalCompositeOperation='source-over';
  return {tile,x:left/res,y:top/res,w:tile.width/res,h:tile.height/res};
 }
 for(const leaf of leaves){const patch=cutout(leaf);if(patch)patches.set(leaf,patch);}

 const camera=record.camera||{},rim=camera.rim;
 const rad=Math.PI/180,homeYaw=0;
 const homePitch=clamp(Number.isFinite(camera.elevation_deg)?camera.elevation_deg:(record.view==='top'?90:0),-90,90)*rad;
 const roll=(Number.isFinite(camera.roll_deg)?camera.roll_deg:0)*rad;
 const homeSin=Math.sin(homePitch),homeCos=Math.cos(homePitch),cr=Math.cos(roll),sr=Math.sin(roll);
 const depthField=canopy?.depth;
 const depthValid=depthField&&Number.isInteger(depthField.width)&&Number.isInteger(depthField.height)&&
  depthField.width>1&&depthField.height>1&&depthField.width<=96&&depthField.height<=96&&
  Array.isArray(depthField.samples)&&depthField.samples.length===depthField.width*depthField.height&&depthField.units===4096;
 const observedRim=!!(rim&&Array.isArray(rim.center)&&rim.center.length===2&&rim.center.every(Number.isFinite)&&
  Number.isFinite(rim.diameter)&&rim.diameter>0);
 const showContainer=observedRim;

 function surface(faces,points,color,options={}){
  const {twoSided=false,gloss=0,line=false,width=.6,opacity=1}=options;
  let shade=1,shine=0;
  if(!line){
   let normal=cross(sub(points[1],points[0]),sub(points[2],points[0]));
   if(Math.hypot(...normal)<1e-10&&points.length===4)normal=cross(sub(points[2],points[0]),sub(points[3],points[0]));
   normal=unit(normal);
   const l=dot(normal,light),diff=twoSided?Math.abs(l):Math.max(0,l);
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
  const sampled=camera.rim?.rgb;
  const dark=Array.isArray(sampled)&&sampled.length===3?sampled.map(v=>clamp(v*1.22+7,9,210)):[60,62,56];
  const rim=dark.map(v=>clamp(v+10,12,220)),soil=[76,58,42];
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
    const angle=k*tau/n+seed(k,j)*tau/n,rr=Math.sqrt(seed(k,j+9))*.87*r;
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
 const photoLight=leaves.map(s=>.2126*s.rgb[0]+.7152*s.rgb[1]+.0722*s.rgb[2]).sort((a,b)=>a-b);
 const exposure=clamp(139/(photoLight[Math.floor(count/2)]||139),.68,1.55);
 function leafMaterial(s){
  return s.rgb.map((v,i)=>clamp(v*exposure+(i===1?3:0),18,218));
 }
 function leafFaces(faces,s,at,veins=true){
  const color=leafMaterial(s),rows=count>85?20:28,cols=count>85?4:6;
  const grid=Array.from({length:rows+1},(_,j)=>Array.from({length:cols+1},(_,k)=>at(j/rows,2*k/cols-1)));
  for(let j=0;j<rows;j++)for(let k=0;k<cols;k++){
   const t=(j+.5)/rows,edge=Math.abs((k+.5)/cols*2-1),jitter=seed(j+13*s.center[0],k+17*s.center[1])-.5;
   const rgb=lift(color,.94+.07*Math.sin(Math.PI*t)-.045*edge+.018*jitter+(k<cols/2 ? .025 : 0));
   surface(faces,[grid[j][k],grid[j+1][k],grid[j+1][k+1],grid[j][k+1]],rgb,{twoSided:true,gloss:7});
  }
  if(!veins)return;
  const vein=css(color.map((v,i)=>mix(v,i===0?167:i===1?190:111,.27)));
  const rib=(path,width,opacity)=>faces.push({points:path,color:vein,line:true,width,opacity});
  for(let j=0;j<rows;j++)rib([at(j/rows,0),at((j+1)/rows,0)],.55,.58-.25*j/rows);
  for(let j=0;j<6;j++)for(const sign of [-1,1]){
   const u=.15+j*.12,tip=Math.min(.974,u+.18-j*.01),edge=.82+seed(j,sign)*.13;
   const path=[at(u,0),at(mix(u,tip,.4),sign*.38),at(mix(u,tip,.72),sign*.70),at(tip,sign*edge)];
   for(let i=1;i<path.length;i++)rib([path[i-1],path[i]],.34,.34);
  }
 }
 function paintPatch(ctx,f,q){
  const [a,b,c,d]=q,tile=f.image,u=f.u0||0,v=f.v0||0,w=f.uw||tile.width,h=f.vh||tile.height;
  const draw=(p,r,t,lower)=>{
   const xx=(lower?r[0]-t[0]:r[0]-p[0])/w,xy=(lower?r[1]-t[1]:r[1]-p[1])/w;
   const yx=(lower?t[0]-p[0]:t[0]-r[0])/h,yy=(lower?t[1]-p[1]:t[1]-r[1])/h;
   if(Math.abs(xx*yy-xy*yx)<1e-7)return;
   ctx.save();
   if(!f.flat){
    const cx=(p[0]+r[0]+t[0])/3,cy=(p[1]+r[1]+t[1])/3;
    const pts=[p,r,t].map(k=>{const dx=k[0]-cx,dy=k[1]-cy,n=Math.max(1,Math.hypot(dx,dy));
     return [k[0]+.48*dx/n,k[1]+.48*dy/n];});
    ctx.beginPath();ctx.moveTo(...pts[0]);ctx.lineTo(...pts[1]);ctx.lineTo(...pts[2]);ctx.closePath();ctx.clip();
   }
   ctx.transform(xx,xy,yx,yy,p[0]-xx*u-yx*v,p[1]-xy*u-yy*v);
   if(f.flat)ctx.drawImage(tile,0,0);
   else{
    const l=Math.max(0,u-1),top=Math.max(0,v-1),rgt=Math.min(tile.width,u+w+1),bot=Math.min(tile.height,v+h+1);
    ctx.drawImage(tile,l,top,rgt-l,bot-top,l,top,rgt-l,bot-top);
   }
   ctx.restore();
  };
  draw(a,b,c,false);
  if(!f.flat)draw(a,c,d,true);
 }
 function cameraPaint(ctx,faces,project,referenceView=false,rigOpacity=1,backOpacity=0,containerBias=0){
  const drawn=[];
  function add(f,q){
   drawn.push({f,q,d:q.reduce((sum,p)=>sum+p[2],0)/q.length-(f.line ? .0025 : 0)+(f.container?containerBias:0)});
  }
  for(const f of faces){
   if((f.rig&&rigOpacity<=0)||(f.back&&backOpacity<=0))continue;
   const q=f.points.map(project);
   if(!f.patch){add(f,q);continue;}
   const tile=f.patch.tile,n=f.n,n1=n+1;
   if(referenceView){
    add({image:tile,flat:true},[q[0],q[n],q.at(-1),q[n*n1]]);
   }else for(let j=0;j<n;j++)for(let k=0;k<n;k++){
    const i=j*n1+k;
    add({image:tile,u0:tile.width*k/n,v0:tile.height*j/n,uw:tile.width/n,vh:tile.height/n},
     [q[i],q[i+1],q[i+n1+1],q[i+n1]]);
   }
  }
  drawn.sort((a,b)=>b.d-a.d);
  ctx.lineJoin='round';ctx.lineCap='round';
  for(const {f,q} of drawn){
   if(f.image){ctx.globalAlpha=1;paintPatch(ctx,f,q);continue;}
   ctx.globalAlpha=f.opacity*(f.rig?rigOpacity:f.back?backOpacity:1);ctx.beginPath();ctx.moveTo(q[0][0],q[0][1]);
   for(let i=1;i<q.length;i++)ctx.lineTo(q[i][0],q[i][1]);
   if(f.line){ctx.strokeStyle=f.color;ctx.lineWidth=f.width;ctx.stroke();}
   else{
    ctx.closePath();ctx.fillStyle=f.color;ctx.fill();
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
 const measured=patches.size>0,halfX=sourceLong?canopy.width_px/sourceLong/2:0,halfY=sourceLong?canopy.height_px/sourceLong/2:0;
 const xlo=measured?-halfX:Math.min(...xs),xhi=measured?halfX:Math.max(...xs);
 const ylo=measured?-halfY:Math.min(...ys),yhi=measured?halfY:Math.max(...ys);
 const scale=2.65/Math.max(.1,xhi-xlo,yhi-ylo);
 const axes=(x,y)=>[x*cr+y*sr,x*sr-y*cr];
 const corners=[[xlo,ylo],[xhi,ylo],[xlo,yhi],[xhi,yhi]].map(p=>axes(...p));
 const vr=corners.map(p=>p[1]),ur=corners.map(p=>p[0]),vmin=Math.min(...vr),vmax=Math.max(...vr);
 const spread=Math.max(.5,(Math.max(...ur)-Math.min(...ur))*scale);
 const origin=observedRim?axes(...rim.center):[0,vmin*homeCos];
 const canopyHeight=Math.max(.5,(vmax-origin[1])*scale*homeCos+spread*.62*Math.abs(homeSin));
 const potR=observedRim?Math.max(.08,rim.diameter*scale/2):clamp(spread*.355,.38,1.03);
 const potH=clamp(observedRim?(rim.drop||rim.diameter*.80)*scale:.69*canopyHeight,.18,3.8);
 const ordered=[...leaves].sort((a,b)=>axes(...a.center)[0]-axes(...b.center)[0]);
 const world=(u,v,d)=>[u,v*homeCos-d*homeSin,v*homeSin+d*homeCos];
 const cameraPoint=(x,y,d)=>{const [u,v]=axes(x,y);return world((u-origin[0])*scale,(v-origin[1])*scale,d);};

 function boundedDepth(x,y){
  if(!depthValid||!halfX||!halfY)return null;
  const fx=(x/(2*halfX)+.5)*depthField.width-.5,fy=(y/(2*halfY)+.5)*depthField.height-.5;
  if(fx<-.5||fy<-.5||fx>depthField.width-.5||fy>depthField.height-.5)return null;
  let sum=0,w=0;
  for(let j=Math.floor(fy);j<=Math.ceil(fy);j++)for(let i=Math.floor(fx);i<=Math.ceil(fx);i++){
   if(i<0||j<0||i>=depthField.width||j>=depthField.height)continue;
   const z=depthField.samples[j*depthField.width+i],k=(1-Math.abs(fx-i))*(1-Math.abs(fy-j));
   if(k>0&&Number.isFinite(z)&&z!==depthField.missing){sum+=z*k;w+=k;}
  }
  return w>.20?scale*sum/w/depthField.units:null;
 }
 const leafArea=s=>sourceLong&&s.visible_pixels>0?s.visible_pixels/(sourceLong*sourceLong):s.length*s.profile.reduce((sum,p,i)=>i?
  sum+((p[1]-p[0])+(s.profile[i-1][1]-s.profile[i-1][0]))/2:sum,0)/(s.profile.length-1);
 const areas=leaves.map(leafArea),areaTotal=areas.reduce((a,b)=>a+b,0);
 const areaOrder=[...areas].sort((a,b)=>a-b),medianArea=areaOrder[Math.floor(count/2)];
 const medianLength=[...leaves.map(s=>s.length)].sort((a,b)=>a-b)[Math.floor(count/2)];
 const widths=leaves.map(s=>Math.max(...s.profile.map(p=>p[1]-p[0])));
 const ratios=leaves.map((s,i)=>widths[i]/s.length).sort((a,b)=>a-b);
 const bladeRatio=clamp(ratios[Math.floor((count-1)*.72)],.28,.72);

 // Estimate depth inside the canopy where no extra camera view measured it.
 const depthFor=new Map(),levels=Math.max(1,Math.min(8,Math.round(Math.sqrt(count)/2)));
 const byHeight=[...leaves].sort((a,b)=>axes(...a.center)[1]-axes(...b.center)[1]);
 for(let level=0;level<levels;level++){
  const band=byHeight.slice(Math.floor(level*count/levels),Math.floor((level+1)*count/levels));
  band.sort((a,b)=>axes(...a.center)[0]-axes(...b.center)[0]);
  const low=Math.min(...band.map(s=>axes(...s.center)[0]-s.length*.3)),high=Math.max(...band.map(s=>axes(...s.center)[0]+s.length*.3));
  const middle=(low+high)/2,half=Math.max(.025,(high-low)/2);
  band.forEach((s,i)=>{
   const shell=Math.sqrt(Math.max(.07,1-((axes(...s.center)[0]-middle)/half)**2));
   const q=(((i+.5)*.61803398875+(level+.5)*.41421356237)%1)*2-1;
   depthFor.set(s,q*shell*Math.min(potR*1.24,half*scale*.94));
  });
 }
 const maturity=s=>{
  const small=clamp(1-leafArea(s)/Math.max(.00001,medianArea*1.6),0,1);
  const high=clamp((axes(...s.center)[1]-vmin)/Math.max(.01,vmax-vmin),0,1);
  return small*(.38+.62*high);
 };
 const shootCount=Math.min(17,Math.max(1,Math.round(Math.sqrt(count)*1.14)));
 function growthAt(day){
  if(!trajectory.length)return {day:0,area_ratio:1,width_ratio:1,height_ratio:1,new_leaves:0};
  const t=clamp(day,0,trajectory.at(-1).day),i=Math.min(Math.floor(t),trajectory.length-1);
  const a=trajectory[i],b=trajectory[Math.min(i+1,trajectory.length-1)],f=t-a.day;
  return Object.fromEntries(['day','area_ratio','width_ratio','height_ratio','new_leaves'].map(k=>[k,mix(a[k],b[k],f)]));
 }

 // Future pairs are projected leaves, never additional measurements.
 const lastGrowth=trajectory.at(-1),futureLeaves=[];
 const maxNew=Math.min(200-count,Math.max(0,Math.floor(lastGrowth?.new_leaves||0)));
 for(let pair=0;pair<Math.ceil(maxNew/2);pair++){
  const threshold=pair*2+1;
  const at=trajectory.findIndex(p=>p.new_leaves>=threshold);
  if(at<1)continue;
  const a=trajectory[at-1],b=trajectory[at];
  const born=a.day+(threshold-a.new_leaves)/Math.max(1,b.new_leaves-a.new_leaves);
  for(let side=0;side<2&&futureLeaves.length<maxNew;side++){
   const stem=pair%shootCount,node=Math.floor(pair/shootCount),angle=node*Math.PI/2+side*Math.PI+stem*.63;
   const length=medianLength*(.86+.23*seed(pair,side+4));
   const width=clamp(Math.sqrt(medianArea)/Math.max(medianLength,.00001)*1.5,.30,.62)*length;
   const profile=Array.from({length:15},(_,i)=>{
    const u=i/14,w=width*.5*Math.sin(Math.PI*u)**.73*(.91+.11*Math.cos(4*Math.PI*u));
    return [-w,w];
   });
   const source=leaves[(pair*17+side*7)%count];
   futureLeaves.push({center:[0,0],axis:[1,0],length,profile,rgb:source.rgb,
    born,stem,node,angle,projected:true,id:count+futureLeaves.length+1});
  }
 }
 function stemAt(stem,y){
  const t=clamp(y/stem.top,0,1),ease=t*(1.18-.18*t);
  return [mix(stem.x0,stem.x1,ease)+Math.sin(t*Math.PI)*stem.lean,y,mix(stem.z0,stem.z1,ease)];
 }
 function grow(day){
  const state=growthAt(day),faces=[],height=canopyHeight*state.height_ratio;
  if(showContainer)pot(faces,potR,potH);
  for(const face of faces)face.container=true;
  const stems=[],n=shootCount,visible=[...leaves];
  for(let i=0;i<n;i++){
   const b=ordered[Math.min(count-1,Math.floor((i+.5)*count/n))];
   const ax=(axes(...b.center)[0]-origin[0])*scale;
   const layer=((i*.61803398875+.29)%1)*2-1;
   const radius=Math.sqrt(Math.max(.10,1-(ax/(spread*.55))**2));
   const stem={x0:ax*.48,x1:ax*.95*state.width_ratio,z0:layer*radius*potR*.74,z1:layer*radius*potR*1.04*state.width_ratio,
    lean:(seed(i,8)-.5)*.19,top:height,max:0};
   stems.push(stem);
  }
  const development=1-Math.exp(-day/Math.max(1,growth?.leaf_maturation_days||5));
  const extra=Math.max(0,state.area_ratio-1)*areaTotal;
  const emerging=futureLeaves.map(s=>{
   const age=Math.max(0,day-s.born),t=clamp(age/Math.max(1,growth?.leaf_maturation_days||5),0,1);
   return {s,opening:t*t*(3-2*t)};
  }).filter(p=>p.opening>.001);
  const proposed=emerging.reduce((sum,p)=>sum+leafArea(p.s)*p.opening,0);
  const newBudget=Math.min(extra*.48,proposed),newScale=proposed?Math.sqrt(newBudget/proposed):0;
  const available=Math.max(0,extra-newBudget);
  const weights=leaves.map(s=>.05+.95*maturity(s));
  const weightTotal=weights.reduce((sum,w,i)=>sum+w*areas[i],0);
  const leafFactors=leaves.map((s,i)=>Math.sqrt(Math.max(.08,state.area_ratio<1?state.area_ratio:
   1+available*weights[i]/Math.max(.00001,weightTotal))));

  for(const [index,s] of leaves.entries()){
   const factor=leafFactors[index],young=maturity(s);
   const anchor=blade(s,(x,y)=>[x,y])(0,0);
   const c=s.center;
   const r=seed(c[0],c[1]),rnd=seed(c[1],c[0]);
   const depthPrior=(depthFor.get(s)||0)*homeCos-canopyHeight*(.32+.49*r)*homeSin;
   const midpoint=boundedDepth(...c);
   const depthBase=-canopyHeight*.55*homeSin;
   const depth=midpoint===null?depthPrior:depthBase+midpoint;
   const anchorWorld=cameraPoint(...anchor,depth);
   const base=anchorWorld;
   const nodeY=Math.max(.025,base[1]-.034-s.length*scale*.13);
   let chosen=stems[0],dist=Infinity;
   for(const stem of stems){
    const p=stemAt(stem,nodeY),d=Math.hypot(p[0]-base[0],.87*(p[2]-base[2]));
    if(d<dist){dist=d;chosen=stem;}
   }
   let node=stemAt(chosen,nodeY);
   const fold=(.10+.18*r)*(1-.45*young*development)*(rnd<.45?-1:1);
   const aspect=widths[index]/s.length,foreshortening=Math.sqrt(Math.max(0,bladeRatio**2-aspect**2))/Math.max(.065,aspect);
   const sweep=(rnd-.5)*1.5,bank=(r<.5?-1:1)*clamp(.34+.92*foreshortening+.55*seed(index,11),.34,3.0);
   const plane=(x,y,u,v,w)=>{
    const arc=Math.sin(Math.PI*u);
    const rib=Math.exp(-v*v*45)*arc*w*.025;
    const bend=scale*factor*(s.length*(.12*arc-.085*u*u)+w*(.17*(1-v*v)*arc+fold*v)+rib);
    const dx=x-anchor[0],dy=y-anchor[1],long=dx*s.axis[0]+dy*s.axis[1],across=dy*s.axis[0]-dx*s.axis[1];
    const relief=bend+scale*factor*(long*sweep+across*bank);
    const local=boundedDepth(x,y);
    const d=local===null?depth+relief:depthBase+local+relief*.12;
    const q=cameraPoint(x,y,d);
    return [anchorWorld[0]*state.width_ratio+(q[0]-anchorWorld[0])*factor,
            anchorWorld[1]*state.height_ratio+(q[1]-anchorWorld[1])*factor,
            anchorWorld[2]*state.width_ratio+(q[2]-anchorWorld[2])*factor];
   };
   const at=blade(s,plane);
   const root=at(0,0);
   const reach=Math.hypot(root[0]-node[0],root[2]-node[2]);
   const jointY=Math.max(.014,Math.min(nodeY,root[1]-.028-.39*reach));
   chosen.max=Math.max(chosen.max,jointY);
   node=stemAt(chosen,jointY);
   const elbow=node.map((v,i)=>mix(v,root[i],.57)+(i===1 ? .014+.05*reach : 0));
   const stalk=clamp(s.length*scale*.028,.003,.013);
   const petioleStart=faces.length;
   tube(faces,node,elbow,stalk,stalk*.80,[101,133,68]);
   tube(faces,elbow,root,stalk*.80,stalk*.56,[104,137,70]);
   if(measured)for(let j=petioleStart;j<faces.length;j++)faces[j].rig=true;
   const patch=patches.get(s);
   if(patch){
    const n=depthValid?5:(Math.max(patch.tile.width,patch.tile.height)>48?3:2),points=[];
    for(let j=0;j<=n;j++)for(let k=0;k<=n;k++){
     const x=patch.x+patch.w*k/n,y=patch.y+patch.h*j/n,dx=x-c[0],dy=y-c[1];
     const u=clamp(.5+(dx*s.axis[0]+dy*s.axis[1])/s.length,0,1);
     const [lo,mid,hi]=samples(s,u),a=dy*s.axis[0]-dx*s.axis[1];
     const v=clamp((a-mid)/Math.max(.0005,a<mid?mid-lo:hi-mid),-1,1);
     points.push(plane(x,y,u,v,Math.max(0,hi-lo)));
    }
    faces.push({patch,points,n});
    const faceWidth=Math.min(widths[index],s.length*bladeRatio*1.22);
    const back=(u,v)=>{
     const mid=samples(s,u)[1],span=faceWidth*Math.sin(Math.PI*u)**.80;
     const side=mid+span*v*.5,t=(u-.5)*s.length;
     const x=c[0]+s.axis[0]*t-s.axis[1]*side,y=c[1]+s.axis[1]*t+s.axis[0]*side;
     const p=plane(x,y,u,v,span);
     p[1]-=.012*homeSin;p[2]+=.012*homeCos;
     return p;
    };
    const underside=faces.length,steps=8;
    for(let j=0;j<steps;j++)for(const k of [-1,0]){
     const a=j/steps,b=(j+1)/steps;
     surface(faces,[back(a,k),back(b,k),back(b,k+1),back(a,k+1)],
      lift(s.rgb,k<0?1.06:.98),{twoSided:true,gloss:2});
    }
    for(let j=underside;j<faces.length;j++)faces[j].back=true;
   }else leafFaces(faces,s,at,s.length*scale>.035);
  }
  const cohortNodes=new Map();
  for(const {s,opening} of emerging){
   const stem=stems[s.stem],factor=Math.sqrt(opening)*newScale;
   if(factor<.012)continue;
   const nodeId=s.stem+':'+s.node;
   if(!cohortNodes.has(nodeId))cohortNodes.set(nodeId,stemAt(stem,stem.max+.025+s.node*.025*development));
   const tip=cohortNodes.get(nodeId);
   const length=s.length*scale*factor,ca=Math.cos(s.angle),sa=Math.sin(s.angle);
   const stalk=length*.18,base=[tip[0]+ca*stalk,tip[1]+stalk*.40,tip[2]+sa*stalk];
   const at=blade(s,(x,y,u,v,w)=>{
    const along=u*length,across=y*scale*factor*(.18+.82*opening);
    const arch=Math.sin(Math.PI*u)*length*.13,uplift=(1-opening)*length*u*.85;
    return [base[0]+ca*along-sa*across,base[1]+uplift+arch-w*scale*factor*.06*v*v,
     base[2]+sa*along+ca*across];
   });
   tube(faces,tip,base,clamp(length*.022,.001,.005),.0015,[99,134,66]);
   leafFaces(faces,s,at,length>.025);
   if(opening>.08)visible.push(s);
   stem.max=Math.max(stem.max,tip[1]+.014);
  }
  for(const stem of stems){
   const stemStart=faces.length;
   let last=stemAt(stem,-.052);
   const end=stem.max+.024;
   for(let j=1;j<=9;j++){
    const t=j/9,p=stemAt(stem,end*t),r=.010*(1-.76*t);
    tube(faces,last,p,r+.0009,r,[112,137,72],7);last=p;
   }
   if(measured)for(let j=stemStart;j<faces.length;j++)faces[j].rig=true;
  }
  return {faces,height,visible};
 }

 let yaw=homeYaw,pitch=homePitch,drag=null,scene=null,queued=false,requestedDay=0,drawnDay=-1;
 function render(){
  if(canvas.hidden)return;
  const {width:w,height:h}=canvas.getBoundingClientRect(),dpr=Math.min(window.devicePixelRatio||1,2);
  if(!w||!h)return;
  if(drawnDay!==requestedDay){scene=grow(requestedDay);drawnDay=requestedDay;}
  const cw=Math.round(w*dpr),ch=Math.round(h*dpr);
  if(canvas.width!==cw||canvas.height!==ch){canvas.width=cw;canvas.height=ch;}
  const ctx=canvas.getContext('2d');
  if(!ctx)return;
  ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);
  const actualFrame=canopy?.frame?.rect;
  const hasFrame=referencePhoto&&Array.isArray(actualFrame)&&actualFrame.length===4&&
   actualFrame.every(Number.isFinite)&&actualFrame[2]>0&&actualFrame[3]>0;
  const frame=hasFrame?actualFrame:[xlo-.055,ylo-.055,xhi-xlo+.11,yhi-ylo+.11];
  const midX=frame[0]+frame[2]/2,midY=frame[1]+frame[3]/2;
  const focus=cameraPoint(midX,midY,-canopyHeight*.55*homeSin);
  const development=growthAt(requestedDay);
  const margin=Math.max(1,development.width_ratio||1,development.height_ratio||1);
  const focal=Math.min((w-20)/(frame[2]*scale*margin),(h-20)/(frame[3]*scale*margin));
  const c=Math.cos(yaw),s=Math.sin(yaw),cp=Math.cos(pitch),sp=Math.sin(pitch);
  const project=p=>{
   const px=p[0]-focus[0],py=p[1]-focus[1],pz=p[2]-focus[2];
   const x=px*c+pz*s,z=-px*s+pz*c;
   const v=py*cp+z*sp,d=-py*sp+z*cp;
   return [w/2+(cr*x+sr*v)*focal,h/2+(sr*x-cr*v)*focal,d];
  };
  const paper=(img,box,alpha=1)=>{
   ctx.globalAlpha=alpha;
   ctx.drawImage(img,w/2+(box[0]-midX)*focal*scale,h/2+(box[1]-midY)*focal*scale,
    box[2]*focal*scale,box[3]*focal*scale);
   ctx.globalAlpha=1;
  };
  const dyaw=Math.atan2(Math.sin(yaw-homeYaw),Math.cos(yaw-homeYaw));
  const turn=Math.hypot(dyaw,pitch-homePitch),atHome=turn<1e-6;

  // At the original angle and day zero, show the actual captured pixels.
  if(atHome&&!requestedDay&&hasFrame){paper(referencePhoto,frame);return;}
  if(showContainer){
   const floor=project([0,-potH-.025,0]),rw=potR*focal*.93,rh=rw*(.16+.46*Math.abs(sp));
   ctx.save();ctx.translate(floor[0],floor[1]+2);ctx.rotate(roll);ctx.scale(rw,rh);
   const shadow=ctx.createRadialGradient(.12,.04,.1,.12,.04,1.22);
   shadow.addColorStop(0,'rgba(38,54,41,.30)');shadow.addColorStop(1,'rgba(51,70,56,0)');
   ctx.fillStyle=shadow;ctx.fillRect(-1.15,-1.22,2.5,2.44);ctx.restore();
  }
  const reverse=clamp((turn-.09)/1.04,0,1),bias=measured?3*clamp(1-turn/.42,0,1):0;
  cameraPaint(ctx,scene.faces,project,atHome,.72*clamp(turn/.65+requestedDay*.075,0,1),reverse*reverse*(3-2*reverse),bias);
  if(atHome&&!requestedDay&&photographedColour)paper(photographedColour,[-halfX,-halfY,2*halfX,2*halfY]);
  if(!requestedDay&&hasFrame&&turn<.11){
   const k=1-turn/.11;paper(referencePhoto,frame,k*k*(3-2*k));
  }
 }
 function requestRender(){
  if(!queued){queued=true;requestAnimationFrame(()=>{queued=false;render();});}
 }
 function update(){
  const days=Number(slider.value);
  dayText.textContent=days?`Estimated · +${days} ${days===1?'day':'days'}`:
   slider.disabled?'At capture · more history needed':'At capture';
  if(!count)return;
  requestedDay=days;
  scene=grow(days);drawnDay=days;
  countBadge.textContent=(days||record.count_estimated?'≈':'')+scene.visible.length;
  toggle.title=days?'Illustrated leaves at the selected day; future leaves are estimates.':
   record.count_estimated?'Leaf count estimated automatically':'Visible leaves in the source photo';
  list.replaceChildren();
  if(!tray.hidden)drawTiles();
  requestRender();
 }
 function drawTiles(){
  for(const [i,s] of (scene?.visible||leaves).entries()){
   const tile=el('canvas',{width:'132',height:'84','aria-hidden':'true'});
   const item=el('li',{'aria-label':'Leaf '+(i+1)},tile,el('span',{'aria-hidden':'true'},String(i+1)));
   list.append(item);
   const ctx=tile.getContext('2d');if(!ctx)continue;
   const patch=patches.get(s);
   if(patch){
    const f=Math.min(106/patch.tile.width,64/patch.tile.height);
    const w=patch.tile.width*f,h=patch.tile.height*f;
    ctx.drawImage(patch.tile,(132-w)/2,(84-h)/2,w,h);
    continue;
   }
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
  yaw+=(e.clientX-drag.x)*.011;pitch=clamp(pitch+(e.clientY-drag.y)*.010,-Math.PI/2,Math.PI/2);
  drag.x=e.clientX;drag.y=e.clientY;requestRender();
 });
 for(const type of ['pointerup','pointercancel','lostpointercapture'])canvas.addEventListener(type,()=>{drag=null;});
 function resetView(){
  if(drag&&canvas.hasPointerCapture?.(drag.id))canvas.releasePointerCapture(drag.id);
  drag=null;yaw=homeYaw;pitch=homePitch;
  if(!tray.hidden)toggleTray();
  slider.value='0';update();
 }
 reset.addEventListener('click',resetView);
 canvas.addEventListener('dblclick',resetView);
 canvas.addEventListener('keydown',e=>{
  if(e.key==='ArrowLeft')yaw-=.13;
  else if(e.key==='ArrowRight')yaw+=.13;
  else if(e.key==='ArrowUp')pitch=clamp(pitch+.08,-Math.PI/2,Math.PI/2);
  else if(e.key==='ArrowDown')pitch=clamp(pitch-.08,-Math.PI/2,Math.PI/2);
  else if(e.key==='Home'){e.preventDefault();resetView();return;}
  else return;
  e.preventDefault();requestRender();
 });
 new ResizeObserver(requestRender).observe(canvas);
 update();
}

// Double-clicking the HTML uses the local snapshot. A server uses the JSON export.
(() => {
 const status=document.getElementById('twin-empty');
 const pair=value=>Array.isArray(value)&&value.length===2&&value.every(Number.isFinite);
 function validLeaf(leaf){
  return leaf&&pair(leaf.center)&&pair(leaf.axis)&&
   Number.isFinite(leaf.length)&&leaf.length>0&&
   Array.isArray(leaf.rgb)&&leaf.rgb.length===3&&leaf.rgb.every(Number.isFinite)&&
   Array.isArray(leaf.profile)&&leaf.profile.length===15&&leaf.profile.every(pair);
 }
 async function show(data){
  const viewer=data?.viewer;
  const leaves=viewer?.latest?.leaves;
  if(!viewer||(viewer.latest!==null&&
     (!Array.isArray(leaves)||leaves.length>200||!leaves.every(validLeaf)))){
   throw new Error('Incompatible digital twin data.');
  }
  const surface=viewer.latest?.canopy;
  async function readPhoto(mime,encoded,width,height){
   if(!['image/png','image/webp'].includes(mime)||typeof encoded!=='string'||encoded.length>14500000||
      !Number.isFinite(width)||!Number.isFinite(height)||Math.min(width,height)<=0)return null;
   try{
    const img=new Image();
    await new Promise((resolve,reject)=>{
     img.onload=resolve;img.onerror=reject;
     img.src='data:'+mime+';base64,'+encoded;
    });
    if(img.width>0&&img.height>0&&Math.max(img.width,img.height)<=1536&&
       Math.abs(img.width*height-img.height*width)<=Math.max(width,height))return img;
   }catch{
    // The measured contours remain usable without a photo texture.
   }
   return null;
  }
  const frame=surface?.frame;
  const [colour,photo]=await Promise.all([
   readPhoto('image/png',surface?.masked_png,surface?.width_px,surface?.height_px),
   readPhoto(frame?.mime,frame?.data,frame?.crop_px?.[2],frame?.crop_px?.[3])
  ]);
  showTwin(viewer,colour,photo);
 }
 async function loadView(){
  if(location.protocol==='file:'){
   const node=document.createElement('script');
   const snapshot=await new Promise((resolve,reject)=>{
    node.onload=()=>resolve(globalThis.BioBoxTwinData);
    node.onerror=()=>reject(new Error('No local display data yet.'));
    node.src='digital_twin.data.js';
    document.head.append(node);
   }).finally(()=>node.remove());
   delete globalThis.BioBoxTwinData;
   if(!snapshot)throw new Error('No local display data yet.');
   return snapshot;
  }
  const response=await fetch('digital_twin.json',{cache:'no-store'});
  if(!response.ok)throw new Error('No saved display data.');
  return response.json();
 }
 loadView().then(show).catch(error=>{
  status.hidden=false;
  status.textContent=(error.message||'Could not read the view.')+
   ' Run python computer_vision_pipeline.py in the project folder, then refresh.';
 });
})();