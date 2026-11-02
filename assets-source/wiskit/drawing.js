const P={O:'#3a1820',o:'#f2913d',h:'#ffb966',s:'#c9612a',c:'#fff0dc',d:'#efc9a0',n:'#ec6f7f',e:'#24121a',b:'#a9dcf7',B:'#4b8fcc',k:'#2d5a9a',w:'#ffffff',a:'#ffd23f',z:'#c8d6ff',y:'#ffe14d',r:'#f0553f',g:'#6fd65a',u:'#4a86e8'};
const NAMES={O:'outline',o:'fur',h:'fur light',s:'stripe',c:'cream',d:'cream shade',n:'pink',e:'pupil',b:'glass',B:'glass shade',k:'collar',w:'glint',a:'signal',z:'fog',y:'aura 1',r:'aura 2',g:'aura 3',u:'aura 4'};
const W=96,H=56,G=H-2,L=36,LT=12,R=5.2,BY=G-8,NX=14,TX=NX+L;
const tok=r=>{let o='';r.trim().split(/\s+/).forEach(t=>{const m=t.match(/^(\d*)(.)$/);o+=m[2].repeat(m[1]?+m[1]:1)});return o};

// head is front-facing, 14 wide; eyes, brows, mouth and whiskers are drawn on top by face()
const HEAD=[
'2. O 8. O 2.',
'. O n O 6. O n O .',
'. O 2n O 4. O 2n O .',
'. O 2o 6O 2o O .',
'. O 2h 2o 2s 4o O .',
'. O 10o O .',
'O 11o s O',
'O 11o s O',
'O 11o s O',
'O 3o 2c 2n 2c 2o s O',
'. O 3o c 2O c 3o O .',
'2. 10O 2.'].map(tok);
const BROW={flat:[[2,5],[3,5],[4,5],[5,5]],focus:[[2,4],[3,4],[4,5],[5,5]],worry:[[2,5],[3,5],[4,4],[5,4]],up:[[2,4],[3,4],[4,4],[5,4]]};

const blank=()=>Array.from({length:H},()=>Array(W).fill('.'));
function put(g,x,y,ch,soft){if(P[ch]&&x>=0&&x<W&&y>=0&&y<H&&(!soft||g[y][x]==='.'))g[y][x]=ch}
const comp=(d,s)=>s.forEach((r,y)=>r.forEach((c,x)=>{if(c!=='.')d[y][x]=c}));
const smooth=t=>t<=0?0:t>=1?1:t*t*(3-2*t);

// spine: walk from the neck to the tail tip, heading th(s) (0 = toward the tail, y grows down)
function turtle(th,rad,len){const pts=[];let x=0,y=0;for(let s=0;s<=len+1e-6;s+=.5){const t=th(s);pts.push({x,y,t,s,r:rad(s)});x+=Math.cos(t)*.5;y+=Math.sin(t)*.5}return pts}
function spine(o){const body=o.th||(()=>0),tb=body(L),curl=o.curl??2.3,sw=o.sway||0,br=o.breath||0,r0=o.tr||R*.86,lt=o.lt||LT;
  const th=s=>s<=L?body(s):tb-(curl+sw*.35)*Math.pow((s-L)/lt,o.tp||1.3);
  const rad=s=>s<=L?R*(.86+.2*Math.sin(Math.PI*s/L))+br*Math.sin(Math.PI*s/L):r0-(r0-1.3)*Math.pow((s-L)/lt,.7);
  return turtle(th,rad,L+lt)}
function place(pts,s,x,y){const p=pts[Math.round(s*2)],dx=x-p.x,dy=y-p.y;pts.forEach(q=>{q.x+=dx;q.y+=dy});return pts}

// colour by position on the tube: u along it, v across it (-1 back, +1 belly). Light from above.
function shade(u,v,end=L+LT){
  if(u>L)return u>end-1.5||Math.floor(u-L)%3===2?'s':'o';
  if(v>.5||(v>.2&&u<7))return 'c';
  if(v<-.68)return 'h';
  if(u>8&&u<L-1&&v<.1&&Math.floor(u)%5===0)return 's';
  return 'o'}
function tube(g,pts,vy=1){const end=pts[pts.length-1].s,best=Array.from({length:H},()=>Array(W).fill(1e9));
  pts.forEach(p=>{const nx=-Math.sin(p.t),ny=Math.cos(p.t),r=p.r;
    for(let y=Math.floor(p.y-r-1);y<=p.y+r+1;y++)for(let x=Math.floor(p.x-r-1);x<=p.x+r+1;x++){
      if(x<0||x>=W||y<0||y>=H)continue;const dx=x+.5-p.x,dy=(y+.5-p.y)/vy,d=Math.hypot(dx,dy);
      if(d<=r&&d<best[y][x]){best[y][x]=d;g[y][x]=shade(p.s,(dx*nx+dy*ny)/r,end)}}})}
// near leg in front, far leg a step behind and darker; legs reach the ground, splay > 0 spreads them
function legs(front,back,pts,list,sh,vy,splay){list.forEach(s=>{const p=pts[Math.round(s*2)],r=(p.r-1)*vy,
  by=p.y+Math.cos(p.t)*r,bx=p.x-Math.sin(p.t)*r,x0=Math.round(bx)-1,y0=Math.floor(by),dir=s<L/2?-splay:splay;
  for(let y=y0;y<=G;y++){const o=Math.round(dir*(y-y0)/2),last=y===G;
    for(const c of[0,1]){put(back,x0+3-sh+o+c,y,last?'d':'s',1);put(front,x0+sh+o+c,y,last?'c':'o',1)}}})}
// a floating arm or leg leaving the belly side of the spine at s
function limb(g,pts,s,ang,len,fur,tip){const p=pts[Math.round(s*2)],sx=p.x-Math.sin(p.t)*p.r*.7,sy=p.y+Math.cos(p.t)*p.r*.7,cs=Math.cos(ang),sn=Math.sin(ang);
  for(let t=0;t<=len;t+=.5){const x=Math.round(sx+cs*t),y=Math.round(sy+sn*t),c=t>len-2?tip:fur;
    put(g,x,y,c);if(Math.abs(cs)>Math.abs(sn))put(g,x,y+1,c);else put(g,x+1,y,c)}}
function outline(g){const add=[];for(let y=0;y<H;y++)for(let x=0;x<W;x++)
  if(g[y][x]==='.'&&[[1,0],[-1,0],[0,1],[0,-1]].some(([a,b])=>{const c=(g[y+b]||[])[x+a];return c&&c!=='.'}))add.push([x,y]);
  add.forEach(([x,y])=>g[y][x]='O')}

function head(g,ox,oy){HEAD.forEach((r,y)=>[...r].forEach((c,x)=>put(g,ox+x,oy+y,c)))}
// eye is 4x3: open (slit pupil), half (lid), down (looks at the floor), closed (line), happy (arc)
function eye(g,X,Y,k,lx){const q=(x,y,c)=>put(g,X+x,Y+y,c);
  if(k==='closed'){for(let x=0;x<4;x++)q(x,1,'O');return}
  if(k==='happy'){q(1,0,'O');q(2,0,'O');q(0,1,'O');q(3,1,'O');return}
  const top=k==='half'?1:0;
  for(let y=0;y<3;y++)for(let x=0;x<4;x++)q(x,y,y<top?'O':'c');
  for(let y=k==='down'?1:top;y<3;y++)q(lx,y,'e')}
function face(g,ox,oy,o){const k=o.eyes||'open',gx=o.gx||0,cl=n=>Math.max(0,Math.min(3,n)),w=o.wh||0;
  BROW[o.brow||'flat'].forEach(([x,y])=>{put(g,ox+x,oy+y,'s');put(g,ox+13-x,oy+y,'s')});
  eye(g,ox+2,oy+6,k,cl(2+gx));eye(g,ox+8,oy+6,k,cl(1+gx));
  if(o.mouth==='open'){put(g,ox+5,oy+10,'O');put(g,ox+6,oy+10,'n');put(g,ox+7,oy+10,'n');put(g,ox+8,oy+10,'O')}
  [7,9].forEach(y=>[-2,-1,14,15].forEach(x=>put(g,ox+x,oy+y+w,'s')))}
function helmet(g,ox,oy,lit){const cx=ox+6.5,cy=oy+5.3,HR=9.4,na=Math.atan2(oy+8-cy,ox+8-cx);
  for(let y=Math.floor(cy-HR-1);y<=cy+HR+1;y++)for(let x=Math.floor(cx-HR-1);x<=cx+HR+1;x++){
    const dx=x+.5-cx,dy=y+.5-cy,d=Math.hypot(dx,dy),a=Math.atan2(dy,dx);let da=Math.abs(a-na);if(da>Math.PI)da=2*Math.PI-da;
    if(d>=HR-.5&&d<HR+.5)put(g,x,y,da<.62?'k':dy<-1?'b':'B');
    else if(da<.62&&d>=HR-1.5&&d<HR-.5)put(g,x,y,'k');
    else if(d>=HR-2.4&&d<HR-1.2&&a>-2.9&&a<-1.9)put(g,x,y,'w',1)}
  const ax=Math.round(cx)+1;let top=0;while(top<H-1&&g[top][ax]!=='b'&&g[top][ax]!=='B')top++;
  for(let k=1;k<=3;k++)put(g,ax,top-k,'B');put(g,ax,top-4,lit?'a':'b');
  return {cx,cy,ax,ay:top-4}}
function sparkle(g,x,y,big){put(g,x,y,'w');[[1,0],[-1,0],[0,1],[0,-1]].forEach(([a,b])=>put(g,x+a,y+b,'a'));if(big)[[2,0],[-2,0],[0,2],[0,-2]].forEach(([a,b])=>put(g,x+a,y+b,'a'))}
const ZG=['zzzz','..z.','.z..','zzzz'];
const zee=(g,x,y)=>ZG.forEach((r,j)=>[...r].forEach((c,i)=>put(g,x+i,y+j,c)));

// rainbow halo: distance from the silhouette (flames reach further up than down), cut into four flickering bands
function aura(g,ph,amp){const d=g.map(r=>r.map(c=>c==='.'?1e9:0));
  for(let y=0;y<H;y++)for(let x=0;x<W;x++){let v=d[y][x];
    if(y){v=Math.min(v,d[y-1][x]+1.8);if(x)v=Math.min(v,d[y-1][x-1]+2.1);if(x<W-1)v=Math.min(v,d[y-1][x+1]+2.1)}
    if(x)v=Math.min(v,d[y][x-1]+1);d[y][x]=v}
  for(let y=H-1;y>=0;y--)for(let x=W-1;x>=0;x--){let v=d[y][x];
    if(y<H-1){v=Math.min(v,d[y+1][x]+1);if(x)v=Math.min(v,d[y+1][x-1]+1.4);if(x<W-1)v=Math.min(v,d[y+1][x+1]+1.4)}
    if(x<W-1)v=Math.min(v,d[y][x+1]+1);d[y][x]=v}
  const B=[[2.6,'y'],[5.2,'r'],[7.8,'g'],[10.4,'u']],A=blank();
  for(let y=0;y<=G;y++)for(let x=0;x<W;x++){if(g[y][x]!=='.')continue;
    const f=1+amp*(.6*Math.sin(x*.8+ph)+.4*Math.sin(x*.33-ph*1.4+y*.25));
    for(const [rr,c] of B)if(d[y][x]<=rr*f){A[y][x]=c;break}}
  return A}
const underlay=(g,A)=>A.forEach((r,y)=>r.forEach((c,x)=>{if(c!=='.'&&g[y][x]==='.')g[y][x]=c}));

function finish(g,ox,oy,o,pts){head(g,ox,oy);face(g,ox,oy,o);const hm=helmet(g,ox,oy,o.ant);
  if(o.fx)o.fx(g,{ox,oy,...hm,pts});
  if(o.aura)underlay(g,aura(g,o.aura.ph,o.aura.amp));return g}
function frame(o){const pts=place(spine(o),...o.anchor),back=blank(),front=blank(),vy=o.vy||1;
  tube(back,pts.filter(p=>p.s>L),vy);tube(front,pts.filter(p=>p.s<=L),vy);
  if(!o.nolegs)legs(front,back,pts,o.legs||[4,L-5],o.sh||0,vy,o.splay||0);
  if(o.parts)o.parts(front,back,pts);
  outline(back);outline(front);const g=blank();comp(g,back);comp(g,front);
  const nk=pts[0];return finish(g,Math.round(nk.x-8)+(o.hx||0),Math.round(nk.y-8)+(o.hy||0),o,pts)}

// the loaf: no spine, a rounded block with the paws tucked under the chin and the tail curled on the end
function loafShade(x,v){if(v>.7)return 's';if(v<-.72)return 'h';if(v<.2&&x%6===3)return 's';return 'o'}
function loaf(o){const rx=21,ry=7.2+(o.b||0)*.5,cx=50,cy=G+.5-ry,body=blank();
  for(let y=0;y<H;y++)for(let x=0;x<W;x++){const dx=x+.5-cx,dy=y+.5-cy;
    if(Math.pow(Math.abs(dx)/rx,3)+Math.pow(Math.abs(dy)/ry,2.4)<=1)body[y][x]=loafShade(x-(cx-rx),dy/ry)}
  outline(body);
  const tl=turtle(s=>-.2-2.9*Math.pow(s/LT,1.3)+(o.sway||0)*.25*Math.min(1,s/LT),s=>2.6-s/LT*1.3,LT).map(p=>({...p,s:p.s+L,x:p.x+cx+rx-4,y:p.y+G-3})),tailG=blank();
  tube(tailG,tl);outline(tailG);
  const g=blank();comp(g,body);comp(g,tailG);
  const ox=cx-rx-3,oy=G-14;
  [[2,5],[8,11]].forEach(([a,b])=>{for(let x=a;x<=b;x++){put(g,ox+x,G-2,'c');put(g,ox+x,G-1,'c');put(g,ox+x,G,'d');put(g,ox+x,G+1,'O')}
    for(let y=G-2;y<=G+1;y++){put(g,ox+a-1,y,'O');put(g,ox+b+1,y,'O')}});
  return finish(g,ox,oy,o,null)}

// body shapes
const arch=(al,a0=6,a1=34)=>s=>s<a0||s>a1?0:-al*Math.sin(2*Math.PI*(s-a0)/(a1-a0));
const low=s=>s<9?-.25:s>16?0:-.25*(1-smooth((s-9)/7));
const wave=ph=>{const y=s=>-3*Math.max(0,Math.sin(2*Math.PI*s/16+ph))*smooth((s-2)/5)*smooth((L-1-s)/5);
  return s=>Math.atan((y(s+.25)-y(s-.25))/.5)};
const span=al=>{const p=spine({th:arch(al)});return p[L*2].x-p[0].x};
const INCH=[0,.45,.9,1.3,.95,.55,.2],SHORT=span(1.3),STRIDE=Math.round(L-SHORT),IX=NX+STRIDE;
const RA=[L,TX,BY],D6=[0,1,2,3,4,5];

const STATES={
  idle:{label:'Loaf',task:'nothing running',note:'bread loaf: paws under the chin, eyes shut, the glass fogs on each breath',ms:520,frames:
    [0,1,2,1].map((b,j)=>loaf({b,eyes:j===3?'half':'closed',brow:'flat',sway:j===2?1:0,ant:false,wh:j===2?1:0,
      fx:(g,h)=>{[[],[[-6,2]],[[-6,1],[-6,2],[-5,3],[-7,3]],[[-6,2],[-5,3]]][j].forEach(([x,y])=>put(g,Math.round(h.cx)+x,Math.round(h.cy)+y,'z',1));
        if(j)zee(g,Math.round(h.cx)+6,Math.round(h.cy)-13-j*2)}}))},
  processing:{label:'Processing',task:'thinking, generating',note:'low crouch, legs splayed, back spiked, inside a flickering rainbow aura',ms:140,frames:
    D6.map(j=>frame({vy:.8,anchor:[L,TX+10,BY+2],curl:1.6,sway:[0,1,2,1,0,1][j]*.5,eyes:'open',brow:'focus',legs:[3,L-4],splay:1.4,ant:j%2===0,wh:[0,1,0,-1,0,1][j],
      aura:{ph:j*1.05,amp:.35+.1*Math.sin(j*1.05)},
      parts:(f,b,pts)=>{for(let i=0;i<7;i++){const p=pts[(7+i*4)*2],x=Math.round(p.x),top=Math.floor(p.y-p.r*.8),h=1+((i+j)%3===0?2:1);
        for(let k=0;k<=h;k++)put(f,x,top+1-k,k===h?'s':'o')}}}))},
  searching:{label:'Searching',task:'looking through the knowledge bank',note:'nose to the ground, eyes down, head sweeps from side to side, tail up',ms:170,frames:
    D6.map(j=>frame({th:low,anchor:RA,curl:1.5,sway:[0,1,2,2,1,0][j]*.5,eyes:'down',brow:'focus',gx:[0,-1,-1,0,1,1][j],hx:[0,-1,-1,0,1,1][j],hy:-1,legs:[5,L-5],ant:j===0||j===3,wh:[0,1,1,0,-1,-1][j]}))},
  done:{label:'Done',task:'result placed on the board',note:'proud stretch, back arched high, happy eyes, open mouth, sparkles',ms:170,frames:
    D6.map(j=>frame({th:arch([1,1.15,1.25,1.25,1.15,1.05][j],5,33),anchor:RA,curl:1.4,sway:[0,1,2,1,0,1][j]*.4,eyes:'happy',brow:'up',mouth:'open',hy:-1,ant:true,wh:[0,-1,0,1,0,-1][j],
      fx:(g,h)=>{const m=h.pts[38];[[m.x-8,m.y-8],[m.x+9,m.y-10],[h.cx-14,h.cy-6]].forEach(([x,y],k)=>{const ph=(j+k*2)%6;if(ph<3)sparkle(g,Math.round(x),Math.round(y),ph===1)})}}))},
  hover:{label:'Hover',task:'generating, drifting',note:'astronaut float: body bowed in a slow C, paws reach forward, one leg kicks out, tail spirals up, no ground',ms:220,frames:
    D6.map(j=>{const ph=j*Math.PI/3;return frame({th:s=>(Math.PI/2)*(1-smooth((s-7)/(L-11)))+.1*Math.sin(ph-s/7),anchor:[0,30,17+[0,-1,-1,0,1,1][j]],curl:4,tp:2.6,lt:20,tr:3.2,sway:Math.sin(ph)*1.1,nolegs:true,
      eyes:j===4?'closed':'open',gx:[0,1,1,0,-1,-1][j],brow:'up',mouth:j%3===1?'open':'flat',ant:j%2===0,wh:[0,1,0,-1,0,1][j],
      parts:(f,b,pts)=>{limb(b,pts,11,2.45+.3*Math.sin(ph+1.5),6,'s','d');limb(b,pts,L-3,1.75+.2*Math.sin(ph),6,'s','d');
        limb(f,pts,7,Math.PI-.45+.35*Math.sin(ph),7,'o','c');limb(f,pts,L-7,2.75+.2*Math.sin(ph+2),10,'o','c')}})})},
  slither:{label:'Slither',task:'roaming, short hops',note:'caterpillar wave rolls toward the head, 1 px per frame',ms:110,move:[1,1,1,1,1,1],frames:
    D6.map(j=>frame({th:wave(j*Math.PI/3),anchor:[0,NX,BY],curl:2.1,sway:(j%3)*.4,sh:[0,1,0,-1,0,1][j],eyes:'open',brow:'flat',gx:-1,wh:[0,1,0,-1,0,1][j]}))},
  inch:{label:'Inchworm',task:'roaming, longer trips',note:'accordion: the back bunches up, then the front reaches · '+STRIDE+' px per cycle',ms:130,move:[0,0,0,0,0,0,STRIDE],frames:
    INCH.map((al,j)=>frame({th:arch(al),anchor:j<4?[0,IX,BY]:[L,IX+SHORT,BY],curl:2.3+al*.4,hy:j>=4?-1:0,legs:[4,L-5],eyes:'open',brow:j>=4?'up':'focus',gx:-1}))}
};
