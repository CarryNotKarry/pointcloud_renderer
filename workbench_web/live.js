/* True XYZ projection during gestures; final shading is rendered by VTK.
   No CDN / external dependencies. Matrices use the same orthographic basis. */
const V={add:(a,b)=>a.map((v,i)=>v+b[i]),sub:(a,b)=>a.map((v,i)=>v-b[i]),
  mul:(a,s)=>a.map(v=>v*s),dot:(a,b)=>a.reduce((s,v,i)=>s+v*b[i],0),
  cross:(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]],
  norm:a=>{const n=Math.hypot(...a);return a.map(v=>v/n);}};
function rotateVector(v,axis,angle){
  axis=V.norm(axis);const c=Math.cos(angle),s=Math.sin(angle);
  return V.add(V.add(V.mul(v,c),V.mul(V.cross(axis,v),s)),V.mul(axis,V.dot(axis,v)*(1-c)));
}
function orbitCamera(camera,dx,dy){
  const offset=V.sub(camera.position,camera.focal_point);
  const yaw=dx*Math.PI, pitch=dy*Math.PI*.67;
  let offset2=rotateVector(offset,[0,0,1],yaw);
  let up=rotateVector(camera.view_up,[0,0,1],yaw);
  const right=V.norm(V.cross(V.mul(offset2,-1),up));
  offset2=rotateVector(offset2,right,pitch);up=rotateVector(up,right,pitch);
  return {...camera,position:V.add(camera.focal_point,offset2),view_up:up};
}
const sphereSprites=new Map();
function sphereSprite(color){
  if(sphereSprites.has(color))return sphereSprites.get(color);
  const s=document.createElement('canvas');s.width=s.height=32;const ctx=s.getContext('2d');
  const gradient=ctx.createRadialGradient(11,9,1,16,16,17);
  gradient.addColorStop(0,'#eef5ff');gradient.addColorStop(.4,color);gradient.addColorStop(1,'#45566f');
  ctx.fillStyle=gradient;ctx.beginPath();ctx.arc(16,16,15,0,Math.PI*2);ctx.fill();sphereSprites.set(color,s);return s;
}
function drawLive(canvas,clouds,camera,radius,color,background,alpha=.55){
  const ctx=canvas.getContext('2d'),width=canvas.width,height=canvas.height;
  ctx.globalAlpha=1;ctx.globalCompositeOperation='source-over';ctx.fillStyle=background;ctx.fillRect(0,0,width,height);
  const view=V.norm(V.sub(camera.focal_point,camera.position)),right=V.norm(V.cross(view,camera.view_up)),up=V.norm(V.cross(right,view));
  const scale=height/(2*camera.parallel_scale),sprite=sphereSprite(color),diameter=Math.max(.8,radius*2*scale);
  const projected=[];
  clouds.forEach(points=>points?.forEach(p=>{const q=V.sub(p,camera.focal_point);
    projected.push([width*.5+V.dot(q,right)*scale,height*.5-V.dot(q,up)*scale,V.dot(q,view)]);}));
  projected.sort((a,b)=>b[2]-a[2]);ctx.globalAlpha=clouds.length>1?alpha:1;
  for(const p of projected)if(p[0]>-diameter&&p[0]<width+diameter&&p[1]>-diameter&&p[1]<height+diameter)
    ctx.drawImage(sprite,p[0]-diameter/2,p[1]-diameter/2,diameter,diameter);
  ctx.globalAlpha=1;
}
