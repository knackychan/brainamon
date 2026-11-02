/* ---------- full art v2 (illustration rare): markup + the etched foil texture ----------
   Uses RAR, TYPE, TOTAL and THUMBS from ../engine.js and the page. The slot/.card/.face structure
   matches cardHTML so HandCard drives it unchanged (same FEEL, same light variables). */
const HOLO_RULE='Gold frame and rainbow foil. Pulled last when a booster is opened.';

function cardFA2(it){
  const R=RAR[it.rar];
  const pips=Array.from({length:6},(_,i)=>`<i class="${i<R.pips?'on':''}"></i>`).join('');
  const rule=it.rar==='holo'?`<div class="fa-rule"><b>Holo rare rule</b><span>${HOLO_RULE}</span></div>`:'';
  return `<div class="slot v-fa2 r-${it.rar}" role="group" aria-label="${it.title}" style="--t:${TYPE[it.cat]};--fy:${it.focus}%">
  <div class="shadow"></div>
  <div class="card">
    <div class="ply" style="--z:-1.2px"></div><div class="ply core" style="--z:-0.4px"></div><div class="ply core" style="--z:0.4px"></div><div class="ply" style="--z:1.2px"></div>
    <div class="face front"><div class="win">
      <div class="artbox"><img class="art" src="${THUMBS[it.key]}" alt="" draggable="false"><div class="fa-mist"></div><div class="foil"></div><div class="fa-etch"></div></div>
      <div class="fa-hd"><span class="fa-stage">Reel</span><h3 class="fa-nm">${it.title}</h3><span class="fa-hp"><small>Rank</small><b>${it.rank}</b></span><span class="fa-type" title="${it.src}">f</span><div class="fa-evo">Saved from ${it.src} · ${it.date}</div></div>
      ${it.isNew?'<span class="fa-new">NEW</span>':''}
      <div class="fa-lo">
        <div class="fa-ab"><span class="fa-pill">Flag</span><b>Interesting</b><em>${it.cat}</em></div>
        <p class="fa-ds">${it.desc}</p>
        ${rule}
      </div>
      <div class="fa-stub">
        <div class="fa-st">
          <div><small>source</small><b><span class="fa-ico">f</span>${it.src}</b></div>
          <div><small>rarity <span class="fa-pips">${pips}</span></small><b class="fa-rv">${R.sym} ${R.label}</b></div>
          <div><small>size</small><b>${it.size}</b></div>
        </div>
        <div class="fa-ft"><span class="fa-code">S01</span><b>${it.id}/${TOTAL}</b><span class="fa-rs">${R.sym}</span><span class="fa-il">Illus. ${it.creator}</span><span class="fa-hx">${it.hex}</span><span class="fa-bc"></span></div>
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

/* The etched texture of an illustration rare: short brush strokes that follow a flow field, drawn once
   to a tile that repeats without seams. It is the light-catching emboss on every v2 card and the mask
   that the rainbow shows through on holo rares. */
(function etchTexture(){
  const S=256,c=document.createElement('canvas');c.width=c.height=S;
  const g=c.getContext('2d');if(!g) return;
  let seed=20261008;const rnd=()=>(seed=seed*16807%2147483647)/2147483647;
  const TAU=Math.PI*2;
  const flow=(x,y)=>Math.sin(x/S*TAU*2)*1.25+Math.cos(y/S*TAU*3)*1.05+Math.sin((x+y)/S*TAU)*.6+.5;
  g.lineCap='round';g.lineJoin='round';
  for(let i=0;i<1400;i++){
    let x=rnd()*S,y=rnd()*S;const steps=3+Math.floor(rnd()*9),pts=[[x,y]];
    for(let s=0;s<steps;s++){const a=flow(x,y);x+=Math.cos(a)*2.2;y+=Math.sin(a)*2.2;pts.push([x,y]);}
    g.strokeStyle=`rgba(255,255,255,${(.25+rnd()*.65).toFixed(2)})`;g.lineWidth=.4+rnd()*.9;
    for(const ox of [-S,0,S]) for(const oy of [-S,0,S]){   // draw every stroke in the 3x3 neighbourhood so the tile wraps
      g.beginPath();g.moveTo(pts[0][0]+ox,pts[0][1]+oy);
      for(let k=1;k<pts.length;k++) g.lineTo(pts[k][0]+ox,pts[k][1]+oy);
      g.stroke();
    }
  }
  // A plain rule, not a CSS variable: the light restyles these layers every frame, and through var()
  // each restyle would re-read the whole data URL (measured: 2.5 s of style per 10 s of hover).
  try{
    const u=`url(${c.toDataURL('image/png')})`,st=document.createElement('style');
    st.textContent=`.fa-etch{background-image:${u}}.v-fa2.r-holo .foil{-webkit-mask-image:${u};mask-image:${u}}`;
    document.head.appendChild(st);
  }catch(_){}
})();
