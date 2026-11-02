/* ---------- shared: item data, card markup, hand-held 3D motion ---------- */
const RAR={
  holo:{label:'Holo rare',sym:'★',pips:6},
  uncommon:{label:'Uncommon',sym:'◆',pips:4},
  common:{label:'Common',sym:'●',pips:3},
};
const TYPE={Fitness:'#58b35a',SEO:'#9b6fd3','AI tools':'#e7b51f',Blender:'#ec7a3a'};
const TOTAL=1532;

function cardHTML(it,variant){
  const R=RAR[it.rar];
  const pips=Array.from({length:6},(_,i)=>`<i class="${i<R.pips?'on':''}"></i>`).join('');
  return `<div class="slot v-${variant} r-${it.rar}" role="group" aria-label="${it.title}" style="--t:${TYPE[it.cat]};--fy:${it.focus}%">
  <div class="shadow"></div>
  <div class="card">
    <div class="ply" style="--z:-1.2px"></div><div class="ply core" style="--z:-0.4px"></div><div class="ply core" style="--z:0.4px"></div><div class="ply" style="--z:1.2px"></div>
    <div class="face front"><div class="win">
      <div class="artbox"><img class="art" src="${THUMBS[it.key]}" alt="" draggable="false"><div class="foil"></div>${it.isNew?'<span class="new">NEW</span>':''}<span class="dim">${it.size}</span></div>
      <div class="hd"><span class="stage">Reel</span><h3 class="nm">${it.title}</h3><span class="hp"><small>Rank</small><b>${it.rank}</b></span><span class="type" title="${it.src}">f</span><div class="evo">Saved from ${it.src} · ${it.date}</div></div>
      <div class="strip">No. ${it.id} · ${it.cat} specimen · ${it.size} px</div>
      <div class="pn">
        <div class="ab"><span class="pill">Flag</span><b>Interesting</b><em>${it.cat}</em></div>
        <p class="ds">${it.desc}</p>
        <div class="st">
          <div><small>source</small><b><span class="ico">f</span>${it.src}</b></div>
          <div><small>rarity <span class="pips">${pips}</span></small><b class="rv">${R.sym} ${R.label}</b></div>
          <div><small>size</small><b>${it.size}</b></div>
        </div>
        <div class="ft"><span class="set"></span><b>${it.id}/${TOTAL}</b><span class="rs">${R.sym}</span><span class="il">Illus. ${it.creator}</span><span class="hx">${it.hex}</span><span class="bc"></span></div>
      </div>
    </div><div class="sheen"></div><div class="glare"></div></div>
    <div class="face back"><div class="bk">
      <div class="word">CONTENT<br>MANAGER</div>
      <div class="emb"></div>
      <div class="sub">Specimen series 01</div>
    </div><div class="glare"></div></div>
  </div>
</div>`;
}

/* Inspect model.
   Hovering is holding the card up to look at it: the card turns to follow the pointer, so the part
   under the pointer swings toward you, and it rolls a little as you move toward a corner, the way a
   wrist turns. Moving fast adds torque (roll) and a slight shear that settle back. Every value chases
   its target through a damped spring, so the card lags, overshoots and settles like a real object.
   Clicking does not flip a card; flipTo() is only used by the booster to reveal the pull.
   Balatro touches: at rest every card floats and sways on its own slow rhythm, and when the pointer
   arrives the card pops (a springy scale bounce) with a quick wiggle before it settles into the tilt. */
const IO='IntersectionObserver' in window?new IntersectionObserver(es=>es.forEach(e=>{const h=e.target._hand;if(!h) return;h.onscreen=e.isIntersecting;if(h.onscreen) wake(h);}),{rootMargin:'120px'}):null;
// Card motion is the point of these pages, so it stays on even when the system asks for reduced motion.
// A Motion switch on the page turns it off; the choice is remembered in this browser.
const OS_REDUCED=matchMedia('(prefers-reduced-motion: reduce)').matches;
const MOTION={off:false};
try{MOTION.off=localStorage.getItem('cm-card-motion')==='off';}catch(_){}
const RM={get matches(){return MOTION.off;}};
const ALL=new Set();
document.documentElement.classList.toggle('motion-off',MOTION.off);
function setMotion(on){
  MOTION.off=!on;document.documentElement.classList.toggle('motion-off',!on);
  try{localStorage.setItem('cm-card-motion',on?'on':'off');}catch(_){}
  ALL.forEach(h=>{h.hover=false;h.down=null;h.settle();});
}
function motionSwitch(btn,note){
  const paint=()=>{const on=!MOTION.off;btn.setAttribute('aria-pressed',String(on));btn.textContent=on?'Motion on':'Motion off';};
  btn.addEventListener('click',()=>{setMotion(MOTION.off);paint();});
  paint();
  if(note) note.hidden=!OS_REDUCED;
}
const KEYS=['rx','ry','rz','rl','sk','tx','ty','z','sc','flip'];
// One place to tune how big the motion is. Angles in degrees, distances in px.
const FEEL={tiltY:11,tiltX:9,roll:3,cornerRoll:6,shift:6,lift:16,grow:1.04,pop:.5,wiggle:35,
  spinMax:4,spin:.3,shear:1.5,idleX:1.1,idleY:1.5,idleRoll:.7,idleBob:2};
// The light (highlight, foil, sheen, shadow) is redrawn at most LIGHT_FPS times a second; the card's
// transform keeps the display rate. The final pose always gets its light.
const LIGHT_FPS=60,LIGHT_MS=1000/LIGHT_FPS-1;
// Which layer reads which light variable. The variables are registered with inherits:false (cards.css),
// so each one is written on the layers that read it, not on .slot: a change then restyles those
// layers only, not every element of the card. A new var(--x) in a card rule needs its layer here.
const LIGHT_LAYERS=[['.shadow',['sx','sy','sb','so','ss']],['.face',['fa']],['.artbox',['fa','fo','hx','hy']],
  ['.foil',['fa','fo','hx','hy']],['.sheen',['go','gx']],['.glare',['go','gx','gy','gxb']],['.fa-etch',['go','gx','gy']]];
const ACTIVE=new Set();let ticking=false,lastNow=0;
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const wrap=a=>((a+180)%360+360)%360-180;
function wake(h){ACTIVE.add(h);if(!ticking){ticking=true;lastNow=0;requestAnimationFrame(tick);}}
function tick(now){
  // the first frame after waking has no previous timestamp, so it steps one nominal frame
  const dt=lastNow?Math.min(.05,Math.max(0,(now-lastNow)/1000)):1/60;lastNow=now;
  for(const h of [...ACTIVE]){
    let alive=dt===0,rem=dt;
    while(rem>1e-6){const s=Math.min(rem,1/120);alive=h.integrate(s)||alive;rem-=s;}
    h.render(alive?now:undefined);
    if(!alive) ACTIVE.delete(h);
  }
  if(ACTIVE.size) requestAnimationFrame(tick); else ticking=false;
}

class HandCard{
  constructor(slot,opts={}){
    this.slot=slot;this.card=slot.querySelector('.card');this.opts=opts;
    this.cur={};this.vel={};this.tgt={};
    for(const k of KEYS){this.cur[k]=0;this.vel[k]=0;this.tgt[k]=0;}
    this.cur.flip=this.tgt.flip=opts.flip||0;this.cur.sc=this.tgt.sc=1;
    this.ph=Math.random()*Math.PI*2;this.onscreen=true;this.idle=opts.idle!==false;
    this.lights=[];this.lightAt=-1e9;
    for(const [sel,ks] of LIGHT_LAYERS) for(const el of slot.querySelectorAll(sel)) this.lights.push([el.style,ks]);
    slot._hand=this;ALL.add(this);if(IO) IO.observe(slot);
    this.hover=false;this.down=null;this.dragging=false;
    this.px=.5;this.py=.5;this.vx=0;this.vy=0;this.lx=0;this.ly=0;this.lt=0;
    const on=(t,f)=>slot.addEventListener(t,f.bind(this));
    on('pointerenter',this.enter);on('pointermove',this.move);on('pointerleave',this.leave);
    on('pointerdown',this.press);on('pointerup',this.up);on('pointercancel',this.cancel);
    on('keydown',this.key);
    slot.addEventListener('dragstart',e=>e.preventDefault());
    this.render();
    if(this.idle&&!RM.matches) wake(this);
  }
  get front(){return Math.abs(wrap(this.tgt.flip))<90;}
  locate(e){
    const r=this.slot.getBoundingClientRect(),now=performance.now(),dt=now-this.lt;
    let vx=0,vy=0;
    if(this.lt&&dt>0&&dt<120){vx=(e.clientX-this.lx)/dt*1000;vy=(e.clientY-this.ly)/dt*1000;}
    this.vx=this.vx*.5+vx*.5;this.vy=this.vy*.5+vy*.5;
    this.lx=e.clientX;this.ly=e.clientY;this.lt=now;
    this.px=clamp((e.clientX-r.left)/r.width,0,1);this.py=clamp((e.clientY-r.top)/r.height,0,1);
    return r;
  }
  aim(){
    const t=this.tgt,dx=this.px-.5,dy=this.py-.5;
    t.ry=-dx*2*FEEL.tiltY;               // pointer on the right: the right edge swings toward you
    t.rx=dy*2*FEEL.tiltX;                // pointer near the bottom: the bottom edge swings toward you
    t.rl=dx*FEEL.roll-dx*dy*FEEL.cornerRoll*2;   // heading for a corner rolls the card, like turning a wrist
    t.tx=dx*FEEL.shift+clamp(this.vx*.003,-3,3);
    t.ty=dy*FEEL.shift*.8+clamp(this.vy*.003,-3,3);
    t.z=this.down?FEEL.lift*.4:FEEL.lift;      // lifted toward you while held
    t.sc=this.down?1+(FEEL.grow-1)*.4:FEEL.grow; // and slightly bigger, like a card picked out of the hand
  }
  enter(e){
    if(RM.matches||e.pointerType==='touch') return;
    this.hover=true;this.lt=0;this.locate(e);this.slot.classList.add('is-hover');this.aim();this.juice();wake(this);
  }
  juice(){this.vel.sc+=FEEL.pop;this.vel.rz+=(Math.random()<.5?-1:1)*FEEL.wiggle;}   // the pop and wiggle on arrival
  move(e){
    if(RM.matches) return;
    if(e.pointerType==='touch'&&!this.down) return;
    if(e.pointerType!=='touch'&&!this.hover){this.hover=true;this.slot.classList.add('is-hover');}
    const r=this.locate(e);
    if(this.down&&!this.dragging&&this.opts.drag===true&&Math.hypot(e.clientX-this.down.x,e.clientY-this.down.y)>6) this.startDrag();
    const t=this.tgt;
    if(this.dragging){
      t.flip=this.d0.flip+(e.clientX-this.d0.x)*.55;
      t.rx=clamp(this.d0.rx-(e.clientY-this.d0.y)*.35,-50,50);
      t.sk=clamp(-this.vx/900*2,-3,3);t.z=46;
    }else{
      const dx=e.clientX-(r.left+r.width/2),dy=e.clientY-(r.top+r.height/2);
      const R=(r.width*r.width+r.height*r.height)/4;
      const torque=(dx*this.vy-dy*this.vx)/R;   // stroke direction against the lever arm
      t.rz=clamp(t.rz+torque*FEEL.spin,-FEEL.spinMax,FEEL.spinMax);
      t.sk=clamp(-this.vx/900*FEEL.shear*.6,-FEEL.shear,FEEL.shear);
      this.aim();
    }
    wake(this);
  }
  leave(){
    if(this.dragging) return;
    this.hover=false;this.down=null;this.slot.classList.remove('is-hover','is-down');this.settle();
  }
  settle(){const t=this.tgt;t.rx=0;t.ry=0;t.rl=0;t.tx=0;t.ty=0;t.z=0;t.sk=0;t.sc=1;wake(this);}
  press(e){
    if(e.button!==0) return;
    this.down={x:e.clientX,y:e.clientY,t:performance.now()};
    try{this.slot.setPointerCapture(e.pointerId);}catch(_){}
    if(e.pointerType==='touch'){this.hover=true;this.lt=0;}
    this.locate(e);this.slot.classList.add('is-down');
    if(!RM.matches){this.aim();wake(this);}
  }
  up(e){
    if(!this.down) return;
    const quick=performance.now()-this.down.t<380;
    const wasDrag=this.dragging;
    this.down=null;this.slot.classList.remove('is-down');
    if(wasDrag) this.endDrag();
    else if(quick) this.tap();
    if(e.pointerType==='touch'){this.hover=false;this.settle();}
    else if(this.hover&&!RM.matches){this.aim();wake(this);}
  }
  cancel(){if(this.dragging) this.endDrag();this.down=null;this.hover=false;this.slot.classList.remove('is-down','is-hover');this.settle();}
  key(e){if(this.opts.onTap&&(e.key==='Enter'||e.key===' ')){e.preventDefault();this.tap();}}
  tap(){if(this.opts.onTap) this.opts.onTap(this);}
  flipBy(d){this.flipTo(Math.round((this.tgt.flip+d)/180)*180);}
  flipTo(deg){
    this.tgt.flip=deg;
    if(RM.matches){this.cur.flip=deg;this.render();}
    else{this.vel.z+=320;wake(this);}   // a little hop as it turns over
    if(this.opts.onFace) this.opts.onFace(this.front,this);
  }
  startDrag(){
    const c=this.cur,v=this.vel,t=this.tgt;
    this.dragging=true;this.slot.classList.add('is-drag');
    c.flip+=c.ry;v.flip+=v.ry;c.ry=v.ry=t.ry=0;t.flip=c.flip;
    this.d0={x:this.lx,y:this.ly,flip:c.flip,rx:c.rx};
  }
  endDrag(){
    this.dragging=false;this.slot.classList.remove('is-drag');
    const proj=this.cur.flip+this.vel.flip*.18;   // a flick carries it over
    const was=this.front;this.tgt.flip=Math.round(proj/180)*180;
    if(this.opts.onFace&&was!==this.front) this.opts.onFace(this.front,this);
    if(!this.hover) this.settle();
  }
  integrate(dt){
    const t=this.tgt,c=this.cur,v=this.vel,live=this.hover||!!this.down;
    t.rz*=Math.exp(-dt*3.2);t.sk*=Math.exp(-dt*5);
    let moving=Math.abs(t.rz)>.02||Math.abs(t.sk)>.02;
    const idling=this.idle&&!live&&!this.dragging&&!RM.matches&&this.onscreen;
    if(idling){   // slow, out-of-phase float so a row of cards never moves in lockstep
      const T=performance.now()/1000,p=this.ph;
      t.rx=Math.sin(T*.83+p)*FEEL.idleX;t.ry=Math.sin(T*.61+p*1.7)*FEEL.idleY;t.rl=Math.sin(T*1.07+p*.6)*FEEL.idleRoll;
      t.ty=Math.sin(T*1.31+p*2.3)*FEEL.idleBob;t.tx=0;t.z=0;t.sc=1;moving=true;
    }
    for(const k of KEYS){
      let K,C;
      if(k==='flip'){K=this.dragging?500:85;C=this.dragging?40:10.5;}
      else if(k==='rx'&&this.dragging){K=500;C=40;}
      else if(k==='z'){K=170;C=18;}
      else if(k==='sc'){K=260;C=9;}
      else if(k==='rz'||k==='sk'){K=live?150:110;C=live?11:8;}
      else{K=live?190:120;C=live?15.5:9;}
      v[k]+=(K*(t[k]-c[k])-C*v[k])*dt;c[k]+=v[k]*dt;
      if(Math.abs(t[k]-c[k])>.02||Math.abs(v[k])>.05) moving=true;
    }
    return moving;
  }
  // now: the rAF time (the light waits for LIGHT_MS); left out, the light is written at once
  render(now){
    const c=this.cur,yaw=c.flip+c.ry;
    this.card.style.transform=`translate3d(${c.tx.toFixed(2)}px,${c.ty.toFixed(2)}px,${c.z.toFixed(2)}px) rotateZ(${(c.rz+c.rl).toFixed(3)}deg) rotateX(${c.rx.toFixed(3)}deg) rotateY(${yaw.toFixed(3)}deg) skewX(${c.sk.toFixed(3)}deg) scale(${c.sc.toFixed(4)})`;
    // angle relative to whichever face is toward the viewer drives the light
    const yf=wrap(yaw),yb=wrap(yaw-180),a=Math.abs(yf)<=90?yf:yb;
    const tilt=Math.min(1,(Math.abs(c.rx)+Math.abs(a))/14),held=this.hover||this.down;
    const gx=clamp(50-a*4.2,-30,130),gy=clamp(50+c.rx*4.8,-30,130);   // the highlight sits where the pointer is
    if(now!==undefined&&now-this.lightAt<LIGHT_MS) return;
    this.lightAt=now??-1e9;
    const v={gx:gx.toFixed(1)+'%',gy:gy.toFixed(1)+'%',gxb:(100-gx).toFixed(1)+'%',
      hx:(50+a*6+c.rz*3).toFixed(1)+'%',hy:(50-c.rx*6).toFixed(1)+'%',
      fo:(.12+tilt*.48).toFixed(3),go:((held?.22:0)+tilt*.55).toFixed(3),fa:(125+a*6-c.rx*3).toFixed(1)+'deg',
      sx:(a*.8+c.tx*.6).toFixed(1)+'px',sy:(12+c.z*.5-c.rx*.45+c.ty*.6).toFixed(1)+'px',sb:(12+c.z*.45).toFixed(1)+'px',
      so:clamp(.68-c.z*.006,.25,.8).toFixed(3),ss:(1-c.z*.0012).toFixed(4)};
    for(const [s,ks] of this.lights) for(const k of ks) s.setProperty('--'+k,v[k]);
  }
}
