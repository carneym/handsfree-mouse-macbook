import { Flight, courseAt, clamp } from './flight.mjs';

const $ = id => document.getElementById(id);
const canvas = $('flight'), ctx = canvas.getContext('2d');
const flight = new Flight();
let phase = 'menu', mode = 'practice', lastFrame = 0, width = 0, height = 0;
let countdownEnd = 0, feedbackUntil = 0, feedback = '', feedbackHit = true, lastInput = 0;
let sound = false, audioContext, countdownResume = false;
const stars = Array.from({length:150}, (_,i) => ({x:hash(i*3+1)*2-1,y:hash(i*3+2)*2-1,z:hash(i*3+3),r:.5+hash(i*7)*1.2}));
function hash(seed) { const n=Math.sin(seed*127.1+311.7)*43758.5453;return n-Math.floor(n); }

function resize() {
  width=innerWidth; height=innerHeight;
  const dpr=Math.min(devicePixelRatio||1,2);
  canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);
  ctx.setTransform(dpr,0,0,dpr,0,0);
}
addEventListener('resize',resize);resize();

function setPhase(next) {
  phase=next;
  $('menu').hidden=next!=='menu';$('paused').hidden=next!=='paused';$('results').hidden=next!=='results';
  $('countdown').hidden=next!=='countdown';$('hud').hidden=!['playing','countdown','paused'].includes(next);
  $('pause').hidden=!['playing','countdown'].includes(next);
  document.body.classList.toggle('flying',next!=='menu');
  $('flight-status').textContent={menu:'Awaiting pilot',playing:'Flight systems online',countdown:'Aligning flight systems',paused:'Flight paused',results:'Flight complete'}[next];
  $('flight-tip').textContent=next==='menu'?'Original arcade experiment · separate from calibration':'Steer gently · centre reticle through gates · no clicking needed';
  if(next!=='playing')$('feedback').textContent='';
}
function chooseMode(value) {
  mode=value;
  for(const id of ['practice','trial']) {$(id).classList.toggle('selected',id===value);$(id).setAttribute('aria-pressed',String(id===value));}
}
$('practice').onclick=()=>chooseMode('practice');$('trial').onclick=()=>chooseMode('trial');
$('speed').oninput=()=>{const n=Number($('speed').value);$('pace').textContent=`${n} / ${n<24?'GENTLE':n<43?'CRUISE':'FAST'}`;};

function begin(resume=false) {
  if(!resume)flight.reset({mode,speed:$('speed').value,difficulty:$('difficulty').value});
  countdownResume=resume;countdownEnd=performance.now()+3000;
  // Centre steering on every launch so clicking a menu cannot throw the ship.
  flight.steer(0,0);feedback='';feedbackUntil=0;
  setPhase('countdown');updateHud();
  if(sound)initAudio();
}
$('start').onclick=()=>begin();$('resume').onclick=()=>begin(true);
function pause(reason='Reposition comfortably, then continue.') {
  if(!['playing','countdown'].includes(phase))return;
  $('pause-reason').textContent=reason;$('paused-score').textContent=flight.score.toLocaleString();
  $('paused-accuracy').textContent=flight.accuracy===null?'—':`${flight.accuracy}%`;
  setPhase('paused');
}
$('pause').onclick=()=>pause();
function finish() {
  $('final-score').textContent=flight.score.toLocaleString();$('final-gates').textContent=flight.hits;
  $('final-accuracy').textContent=flight.accuracy===null?'—':`${flight.accuracy}%`;
  $('final-streak').textContent=flight.bestStreak;setPhase('results');
}
$('end').onclick=finish;$('again').onclick=()=>setPhase('menu');
$('home').onclick=e=>{e.preventDefault();if(phase==='playing'||phase==='countdown')pause();else if(phase==='results')setPhase('menu');};
$('fullscreen').onclick=async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen();}catch{ $('fullscreen').textContent='Use browser full screen';}};
document.addEventListener('fullscreenchange',()=>{$('fullscreen').textContent=document.fullscreenElement?'Exit full screen':'Full screen';});
addEventListener('keydown',e=>{
  if(['INPUT','SELECT'].includes(e.target.tagName))return;
  if(e.key==='Escape'||e.key.toLowerCase()==='p'){if(['playing','countdown'].includes(phase))pause();}
});
addEventListener('blur',()=>pause('The game paused when its window lost focus.'));
document.addEventListener('visibilitychange',()=>{if(document.hidden)pause('The game paused while this tab was hidden.');});
canvas.addEventListener('pointermove',e=>{
  if(!['playing','countdown'].includes(phase))return;
  const box=canvas.getBoundingClientRect();
  flight.steer((e.clientX-box.left-box.width/2)/(box.width*.42),-(e.clientY-box.top-box.height/2)/(box.height*.38));
  lastInput=performance.now();
});
canvas.addEventListener('pointerleave',()=>{if(phase==='playing')pause('Pointer left the flight area. Reposition, then continue.');});
canvas.addEventListener('touchmove',e=>e.preventDefault(),{passive:false});
function initAudio(){try{audioContext??=new (window.AudioContext||window.webkitAudioContext)();audioContext.resume().catch(()=>{});}catch{sound=false;}}
$('audio').onclick=()=>{sound=!sound;if(sound)initAudio();$('audio').textContent=sound?'Sound on':'Sound off';$('audio').setAttribute('aria-pressed',String(sound));};
function chime(hit){
  if(!sound||!audioContext)return;
  const t=audioContext.currentTime,osc=audioContext.createOscillator(),gain=audioContext.createGain();
  osc.type=hit?'sine':'triangle';osc.frequency.setValueAtTime(hit?520:110,t);osc.frequency.exponentialRampToValueAtTime(hit?920:65,t+.16);
  gain.gain.setValueAtTime(.0001,t);gain.gain.exponentialRampToValueAtTime(hit?.045:.02,t+.015);gain.gain.exponentialRampToValueAtTime(.0001,t+.24);
  osc.connect(gain);gain.connect(audioContext.destination);osc.start(t);osc.stop(t+.25);
}
function updateHud(){
  $('score').textContent=String(flight.score).padStart(5,'0');$('gates').textContent=String(flight.hits).padStart(2,'0');
  $('streak').textContent=String(flight.streak).padStart(2,'0');
  const sec=Math.max(0,Math.ceil(flight.mode==='trial'?60-flight.elapsed:Math.floor(flight.elapsed)));
  $('timer-label').textContent=flight.mode==='trial'?'TIME LEFT':'FLIGHT TIME';
  $('timer').textContent=`${String(Math.floor(sec/60)).padStart(2,'0')}:${String(sec%60).padStart(2,'0')}`;
}

function render(now) {
  const comfort=$('comfort').checked;
  const preview=phase==='menu';
  const distance=preview?now*.007:flight.distance;
  const player=preview?{x:Math.sin(now*.00017)*1.7,y:.2,vx:0,vy:0}:flight.player;
  const horizon=height*.49, focal=Math.min(width,height)*.95;
  const bg=ctx.createLinearGradient(0,0,0,height);bg.addColorStop(0,'#060915');bg.addColorStop(.46,'#12203b');bg.addColorStop(1,'#070c1a');ctx.fillStyle=bg;ctx.fillRect(0,0,width,height);
  const glow=ctx.createRadialGradient(width*.58,horizon,0,width*.58,horizon,width*.55);glow.addColorStop(0,'#194c6240');glow.addColorStop(.5,'#2c1b5530');glow.addColorStop(1,'#070b1800');ctx.fillStyle=glow;ctx.fillRect(0,0,width,height);
  ctx.save();ctx.translate(width/2,horizon);
  ctx.rotate(comfort?clamp(-player.vx*.0015,-.025,.025):clamp(-player.vx*.004,-.09,.09));ctx.translate(-width/2,-horizon);
  const project=(x,y,z)=>({x:width/2+(x-player.x)*focal/z,y:horizon-(y-player.y)*focal/z});
  for(const s of stars){
    const depth=.15+((s.z-(comfort?distance*.0001:distance*.001))%1+1)%1;
    const x=width/2+s.x*width*.7/depth-player.x*.8,y=horizon+s.y*height*.5/depth;
    if(x<0||x>width||y<0||y>height*.8)continue;
    ctx.fillStyle=`rgba(187,217,250,${.15+.45*(1-depth)})`;ctx.fillRect(x,y,s.r,s.r);
    if(!comfort&&phase==='playing'){ctx.strokeStyle='#9ad6ff22';ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+(x-width/2)*.008,y+(y-horizon)*.008);ctx.stroke();}
  }
  // Distant towers flank a suspended runway. Everything is drawn locally.
  for(let i=39;i>=0;i--){
    const wz=Math.floor(distance/24)*24+i*24+24,z=wz-distance;if(z<5)continue;
    const c=courseAt(wz),side=i%2?-1:1,x=c.x+side*(17+hash(i)*12),top=-7+5+hash(i+13)*22;
    const a=project(x,-7,z),b=project(x+side*3,top,z+8),d=project(x+side*3,-7,z+8),e=project(x,top,z);
    ctx.fillStyle='#111a30';polygon([a,d,b,e]);ctx.fill();ctx.strokeStyle=`rgba(123,122,198,${Math.max(.03,.21-z/2800)})`;ctx.lineWidth=1;ctx.stroke();
    if(i%3===0){ctx.strokeStyle='#ff65984d';ctx.beginPath();ctx.moveTo(e.x,e.y);ctx.lineTo(b.x,b.y);ctx.stroke();}
  }
  const slices=[];
  for(let z=10;z<=780;z+=16){const wz=distance+z,c=courseAt(wz);slices.push({z,c});}
  for(let i=slices.length-2;i>=0;i--){
    const a=slices[i],b=slices[i+1];
    const left=project(a.c.x-12,-7.5,a.z),right=project(a.c.x+12,-7.5,a.z),farL=project(b.c.x-12,-7.5,b.z),farR=project(b.c.x+12,-7.5,b.z);
    ctx.fillStyle=i%2?'#101e30':'#101b2e';polygon([left,right,farR,farL]);ctx.fill();
    ctx.strokeStyle=`rgba(109,249,228,${.05+.22*(1-a.z/800)})`;ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(left.x,left.y);ctx.lineTo(right.x,right.y);ctx.stroke();
    ctx.strokeStyle='#6df9e47d';ctx.lineWidth=1.5;line(left,farL);line(right,farR);
    if(i%3===0){const mid=project(a.c.x,-7.49,a.z),mid2=project(b.c.x,-7.49,b.z);ctx.strokeStyle='#ff8ebd73';ctx.lineWidth=2;line(mid,mid2);}
  }
  // Wireframe arches give depth without a rapidly flashing enclosed tunnel.
  for(let i=17;i>=0;i--){
    const wz=Math.floor(distance/42)*42+(i+1)*42,z=wz-distance;if(z<8)continue;
    const c=courseAt(wz),points=[[-12,-7.5],[-15,-2],[-12,8],[12,8],[15,-2],[12,-7.5]].map(([x,y])=>project(c.x+x,y,z));
    ctx.strokeStyle=`rgba(109,155,227,${.025+.10*(1-z/800)})`;ctx.lineWidth=1;polygon(points);ctx.stroke();
  }
  const gates=preview?Array.from({length:16},(_,i)=>{const z=Math.floor(distance/52)*52+(i+1)*52+30;return{z,...courseAt(z),rx:3.6,ry:2.6};}):flight.gates;
  for(let i=gates.length-1;i>=0;i--){
    const gate=gates[i],z=gate.z-distance;if(z<2||z>850)continue;
    const centre=project(gate.x,gate.y,z),rx=gate.rx*focal/z,ry=gate.ry*focal/z;
    const alpha=clamp(1-z/950,.12,1),colour=i===0?'109,249,228':'143,140,245';
    const points=gateShape(centre.x,centre.y,rx,ry);
    ctx.fillStyle=`rgba(${colour},${.018*alpha})`;polygon(points);ctx.fill();
    ctx.strokeStyle=`rgba(${colour},${alpha*.12})`;ctx.lineWidth=Math.min(15,5+rx*.04);ctx.stroke();
    ctx.strokeStyle=`rgba(${colour},${alpha})`;ctx.lineWidth=i===0?2.5:1.4;ctx.stroke();
    if(i===0){ctx.strokeStyle='#efffffb0';ctx.lineWidth=1;const a=rx*.17;line({x:centre.x-a,y:centre.y},{x:centre.x+a,y:centre.y});line({x:centre.x,y:centre.y-a},{x:centre.x,y:centre.y+a});}
  }
  ctx.restore();
  if(!preview){
    ctx.strokeStyle='#d6fff3aa';ctx.lineWidth=1;const x=width/2,y=horizon;
    ctx.beginPath();ctx.arc(x,y,10,0,Math.PI*2);ctx.stroke();
    for(const [dx,dy]of[[0,-1],[0,1],[-1,0],[1,0]])line({x:x+dx*15,y:y+dy*15},{x:x+dx*23,y:y+dy*23});
    const tx=x+flight.target.x/8*width*.30,ty=y-flight.target.y/5*height*.24;
    ctx.strokeStyle='#6df9e44a';ctx.setLineDash([3,7]);line({x,y},{x:tx,y:ty});ctx.setLineDash([]);
    ctx.strokeStyle='#6df9e4';ctx.beginPath();ctx.arc(tx,ty,4,0,Math.PI*2);ctx.stroke();
  }
  // Low cockpit silhouette keeps the centre of the scene open.
  ctx.fillStyle='#040a14';polygon([{x:0,y:height},{x:0,y:height*.84},{x:width*.21,y:height*.91},{x:width*.31,y:height}]);ctx.fill();
  polygon([{x:width,y:height},{x:width,y:height*.84},{x:width*.79,y:height*.91},{x:width*.69,y:height}]);ctx.fill();
  ctx.strokeStyle='#6df9e44d';ctx.lineWidth=1;line({x:0,y:height*.84},{x:width*.21,y:height*.91});line({x:width,y:height*.84},{x:width*.79,y:height*.91});
}
function polygon(points){ctx.beginPath();ctx.moveTo(points[0].x,points[0].y);for(const p of points.slice(1))ctx.lineTo(p.x,p.y);ctx.closePath();}
function line(a,b){ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();}
function gateShape(x,y,rx,ry){return [[-.65,-1],[.65,-1],[1,-.55],[1,.55],[.65,1],[-.65,1],[-1,.55],[-1,-.55]].map(([px,py])=>({x:x+px*rx,y:y+py*ry}));}

function frame(now){
  const raw=lastFrame?(now-lastFrame)/1000:0;lastFrame=now;
  if(phase==='playing'&&raw>.25)pause('Flight paused during a delayed update.');
  if(phase==='countdown'){
    const remain=countdownEnd-now;
    $('countdown').textContent=remain>0?Math.ceil(remain/1000):'GO';
    if(remain<=0){setPhase('playing');lastInput=now;}
  }
  if(phase==='playing'){
    if(now-lastInput>12000)pause('No steering input for a while. Continue when you are ready.');
    else{
      const events=flight.update(raw);
      for(const event of events){feedbackHit=event.hit;feedback=event.hit?`GATE CLEAR  /  ${flight.streak} CHAIN`:'GATE MISSED  /  KEEP FLYING';feedbackUntil=now+1000;chime(event.hit);}
      updateHud();if(flight.finished)finish();
    }
  }
  $('feedback').textContent=phase==='playing'&&now<feedbackUntil?feedback:'';
  $('feedback').style.color=feedbackHit?'#6df9e4':'#ff9fb9';
  render(now);requestAnimationFrame(frame);
}
setPhase('menu');requestAnimationFrame(frame);
