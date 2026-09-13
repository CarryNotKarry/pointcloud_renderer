'use strict';
const $ = id => document.getElementById(id);
const colors = ['#F07832','#E45464','#259CCA','#7970CE'];
let state, target, result, images = [], mode = 'orbit', editing = -1;
let chain = Promise.resolve(), busy = false;
const geometryCache = new Map();
let cancelGesture = null;
function status(text) { $('status').textContent = text; }
function task(fn) {
  chain = chain.then(async () => {
    busy = true; document.body.classList.add('busy'); status('处理中，请稍候…');
    try { const message=await fn(); status(message||'已自动保存 · 就绪'); }
    catch (e) { status('错误：' + e.message); console.error(e); }
    finally { busy = false; document.body.classList.remove('busy'); }
  });
  return chain;
}
async function api(action, data={}) {
  const response = await fetch('/api/'+action, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || response.statusText);
  return value;
}
function obj() { return state?.objects[target]; }
function element(tag, text, cls) {
  const e = document.createElement(tag); if (text!==undefined) e.textContent=text;
  if (cls) e.className=cls; return e;
}
function controls() {
  $('objects').replaceChildren();
  for (const t of state.targets) {
    const row=element('div',undefined,'item'), check=document.createElement('input'); check.type='checkbox'; check.checked=state.objects[t].enabled;
    check.onchange=()=>task(async()=>{state=await api('update',{target:t,object:{enabled:check.checked}});});
    const b=element('button',t,t===target?'selected':'');
    b.onclick=()=>task(async()=>{target=t;controls();await render();});
    row.append(check,b); $('objects').append(row);
  }
  $('methods').replaceChildren();
  state.methods.forEach((m,i)=>{
    const row=element('div',undefined,'method'), check=document.createElement('input'); check.type='checkbox';check.checked=m.visible;
    check.onchange=()=>task(async()=>{m.visible=check.checked;state=await api('update',{methods:state.methods});await render();});
    const label=element('span',m.label); label.title='双击修改论文标签';
    label.ondblclick=()=>{const value=prompt('论文列标签',m.label);if(value!==null)task(async()=>{m.label=value;state=await api('update',{methods:state.methods});controls();await render();});};
    const up=element('button','↑'),down=element('button','↓');
    function move(j){if(j<0||j>=state.methods.length)return;task(async()=>{[state.methods[i],state.methods[j]]=[state.methods[j],state.methods[i]];state=await api('update',{methods:state.methods});controls();await render();});}
    up.onclick=()=>move(i-1);down.onclick=()=>move(i+1);row.append(check,label,up,down);$('methods').append(row);
  });
  if(!obj())return;
  $('title').textContent=target;
  for(const k of ['azimuth','elevation','roll','zoom','pan_x','pan_y']) $(k).value=obj()[k];
  for(const k of ['color','background','size_scale','shadow_mode','light_preset']) $(k).value=state.style[k];
  $('objectColor').value=obj().color||state.style.color;
  $('sizeSlider').value=state.style.size_scale;
  $('undoRoi').disabled=!(obj().roi_history||[]).length;
}
async function patch(values, rerender=true) {
  state=await api('update',{target,object:values});controls();
  if(rerender)await render();else {paint();roiList();}
}
async function render() {
  if(!obj())return;
  status('正在渲染共享视角…');
  images=[];
  $('panels').replaceChildren(element('div','正在生成 '+target+' 的共享视角预览…','empty'));
  result=await api('render',{target,size:480});state.objects[target]=result.object;
  if(!geometryCache.has(target))geometryCache.set(target,await api('geometry',{target}));
  images=await Promise.all(result.panels.map(async p=>{
    if(!p.image)return {...p,img:null};
    const img=new Image(); await new Promise((resolve,reject)=>{img.onload=resolve;img.onerror=()=>reject(new Error('Preview image failed'));img.src=p.image;});
    return {...p,img};
  }));
  $('radius').textContent='共享半径 '+result.radius.toFixed(6)+' · 正交投影';
  buildPanels();roiList();
}
function buildPanels() {
  $('panels').replaceChildren();
  const overlay=$('layout').value==='overlay';$('alphaLabel').hidden=!overlay;
  const panels=overlay?[{name:'图层叠加',label:'图层叠加 · 用于检查对齐',overlay:true}]:images;
  panels.forEach(p=>{
    const card=element('div',undefined,'panel'),head=element('div',undefined,'panel-head');
    head.append(element('strong',p.label),element('small',p.points?`${p.points.toLocaleString()} pts`:''));
    const canvas=document.createElement('canvas');canvas.width=480;canvas.height=480;canvas._panel=p;
    card.append(head,canvas);
    if(!overlay){const metric=document.createElement('input');metric.className='metric';metric.placeholder='可选指标，例如 HD: 1.333';metric.value=obj().metrics[p.name]||'';
      metric.onchange=()=>{const value=metric.value;task(()=>patch({metrics:{...obj().metrics,[p.name]:value}},false));};card.append(metric);}
    $('panels').append(card);wireCanvas(canvas);
  });paint();
}
function paint(draft=null) {
  for(const canvas of $('panels').querySelectorAll('canvas')){
    const ctx=canvas.getContext('2d');ctx.globalAlpha=1;ctx.globalCompositeOperation='source-over';ctx.fillStyle=state.style.background;ctx.fillRect(0,0,480,480);
    const p=canvas._panel;
    if(p.overlay){let count=0;for(const layer of images){if(!layer.img)continue;ctx.globalCompositeOperation=count?'multiply':'source-over';ctx.globalAlpha=count?+$('alpha').value:1;ctx.drawImage(layer.img,0,0,480,480);count++;}}
    else if(p.img)ctx.drawImage(p.img,0,0,480,480);
    else {ctx.fillStyle='#829299';ctx.font='16px sans-serif';ctx.fillText('Missing / unreadable',150,245);}
    ctx.globalAlpha=1;ctx.globalCompositeOperation='source-over';
    [...obj().rois,...(draft?[draft]:[])].forEach((r,i)=>{ctx.strokeStyle=colors[i%4];ctx.lineWidth=4;ctx.strokeRect(r.x*480,r.y*480,r.w*480,r.h*480);ctx.fillStyle=colors[i%4];ctx.font='13px sans-serif';ctx.fillText('R'+(i+1),r.x*480+4,r.y*480+15);});
  }
}
function position(event,canvas){const b=canvas.getBoundingClientRect();return {x:Math.max(0,Math.min(1,(event.clientX-b.left)/b.width)),y:Math.max(0,Math.min(1,(event.clientY-b.top)/b.height))};}
function paintLive(camera,scale=state.style.size_scale){
  const geometry=geometryCache.get(target);if(!geometry)return;
  for(const canvas of $('panels').querySelectorAll('canvas')){
    const p=canvas._panel;
    const clouds=p.overlay?images.filter(p=>p.img).map(p=>geometry[p.name]):[geometry[p.name]];
    drawLive(canvas,clouds,camera,obj().radius*scale,obj().color||state.style.color,state.style.background,+$('alpha').value);
    const ctx=canvas.getContext('2d');obj().rois.forEach((r,i)=>{ctx.strokeStyle=colors[i];ctx.lineWidth=4;ctx.strokeRect(r.x*480,r.y*480,r.w*480,r.h*480);});
  }
  status('实时几何预览 · 松开后恢复高清光照');
}
function wireCanvas(canvas){
  let start=null,end=null,wheelTimer,baseCamera,currentCamera,frame=0,wheelZoom;
  function cancel(){start=null;cancelAnimationFrame(frame);clearTimeout(wheelTimer);paint();cancelGesture=null;}
  canvas.onpointerdown=e=>{if(busy)return;start=position(e,canvas);end=start;baseCamera=structuredClone(obj().camera);currentCamera=baseCamera;canvas.setPointerCapture(e.pointerId);cancelGesture=cancel;};
  canvas.onpointermove=e=>{if(!start)return;end=position(e,canvas);if(mode==='roi')paint({x:Math.min(start.x,end.x),y:Math.min(start.y,end.y),w:Math.abs(end.x-start.x),h:Math.abs(end.y-start.y)});else {currentCamera=orbitCamera(baseCamera,end.x-start.x,end.y-start.y);cancelAnimationFrame(frame);frame=requestAnimationFrame(()=>paintLive(currentCamera));}};
  canvas.onpointerup=e=>{
    if(!start)return;end=position(e,canvas);const a=start,b=end;start=null;cancelGesture=null;cancelAnimationFrame(frame);
    if(mode==='roi'){
      const r={x:Math.min(a.x,b.x),y:Math.min(a.y,b.y),w:Math.abs(a.x-b.x),h:Math.abs(a.y-b.y)};
      if(r.w<.006||r.h<.006){paint();return;}if(obj().rois.length>=4){status('每个物体最多 4 个框，请先删除一个');paint();return;}
      task(()=>patch({rois:[...obj().rois,r]},false));
    }else{if(Math.abs(b.x-a.x)+Math.abs(b.y-a.y)<.002)return;
      const camera=orbitCamera(baseCamera,b.x-a.x,b.y-a.y);
      const d=V.sub(camera.position,camera.focal_point);
      task(()=>patch({camera,azimuth:Math.atan2(d[1],d[0])*180/Math.PI,elevation:Math.max(-89,Math.min(89,Math.asin(d[2]/Math.hypot(...d))*180/Math.PI))}));}
  };
  canvas.onpointercancel=cancel;
  canvas.onwheel=e=>{e.preventDefault();if(busy||mode==='roi')return;clearTimeout(wheelTimer);wheelZoom=Math.max(.2,Math.min(8,(wheelZoom||obj().zoom)*(e.deltaY<0?1.1:1/1.1)));const camera={...obj().camera,parallel_scale:obj().camera.parallel_scale*obj().zoom/wheelZoom};paintLive(camera);const zoom=wheelZoom;wheelTimer=setTimeout(()=>{wheelZoom=null;task(()=>patch({camera,zoom}));},220);};
}
function roiList(){
  $('rois').replaceChildren();
  obj().rois.forEach((r,i)=>{
    const row=element('div',undefined,'roi-item'),swatch=element('span',undefined,'swatch');swatch.style.background=colors[i];
    const info=element('span',`R${i+1} · 1600 px: x=${Math.round(r.x*1600)}, y=${Math.round(r.y*1600)}, w=${Math.round(r.w*1600)}, h=${Math.round(r.h*1600)}`,'info');
    const edit=element('button','编辑像素'),del=element('button','删除');edit.onclick=()=>openPixels(i);del.onclick=()=>task(()=>patch({rois:obj().rois.filter((_,j)=>j!==i)},false));row.append(swatch,info,edit,del);$('rois').append(row);
    const crops=element('div',undefined,'crops');for(const p of images){if(!p.img)continue;const box=element('div',undefined,'crop'),c=document.createElement('canvas');
      const left=Math.round(r.x*480),top=Math.round(r.y*480),right=Math.round((r.x+r.w)*480),bottom=Math.round((r.y+r.h)*480);
      c.width=Math.max(1,right-left);c.height=Math.max(1,bottom-top);c.getContext('2d').drawImage(p.img,left,top,c.width,c.height,0,0,c.width,c.height);
      const img=new Image();img.src=c.toDataURL();img.style.borderColor=colors[i];box.append(img,element('small',p.label));crops.append(box);}
    $('rois').append(crops);
  });
}
function openPixels(index=-1){if(!obj())return;editing=index;$('pixelSize').value=1600;if(index>=0){const r=obj().rois[index];['px','py','pw','ph'].forEach((id,j)=>$(id).value=Math.round(r[['x','y','w','h'][j]]*1600));}$('pixelDialog').showModal();}
$('savePixel').onclick=()=>task(async()=>{const n=+$('pixelSize').value;if(n<=0)throw new Error('参考边长应大于 0');const r={x:+$('px').value/n,y:+$('py').value/n,w:+$('pw').value/n,h:+$('ph').value/n};const rois=[...obj().rois];if(editing<0)rois.push(r);else rois[editing]=r;await patch({rois},false);$('pixelDialog').close();});
$('addPixel').onclick=()=>openPixels();
$('undoRoi').onclick=()=>{if(!obj())return;task(async()=>{state=await api('undo_rois',{target});controls();paint();roiList();});};
$('clearRois').onclick=()=>{if(obj())task(()=>patch({rois:[]},false));};
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&cancelGesture){cancelGesture();e.preventDefault();}if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='z'&&!/INPUT|TEXTAREA|SELECT/.test(e.target.tagName)&&!busy){e.preventDefault();$('undoRoi').click();}});
$('orbit').onclick=()=>{mode='orbit';$('orbit').classList.add('active');$('roiMode').classList.remove('active');$('hint').textContent='实时拖动旋转；滚轮缩放，松开恢复高清效果。';};
$('roiMode').onclick=()=>{mode='roi';$('roiMode').classList.add('active');$('orbit').classList.remove('active');$('hint').textContent='在任意图上拖出矩形；相同像素区域同步至所有方法。';};
$('layout').onchange=()=>{if(obj())buildPanels();};$('alpha').oninput=()=>paint();
$('refresh').onclick=()=>task(render);
for(const k of ['azimuth','elevation','roll','zoom','pan_x','pan_y'])$(k).onchange=()=>{const v=+$(k).value;task(()=>patch({[k]:v}));};
for(const k of ['color','background','size_scale','shadow_mode','light_preset'])$(k).onchange=()=>{const v=k==='size_scale'?+$(k).value:$(k).value;task(async()=>{state=await api('update',{style:{[k]:v}});await render();});};
$('sizeSlider').oninput=()=>{if(!obj()||busy)return;$('size_scale').value=$('sizeSlider').value;paintLive(obj().camera,+$('sizeSlider').value);};
$('sizeSlider').onchange=()=>{const value=+$('sizeSlider').value;task(async()=>{state=await api('update',{style:{size_scale:value}});controls();await render();});};
$('objectColor').onchange=()=>{const color=$('objectColor').value;task(()=>patch({color}));};
$('clearObjectColor').onclick=()=>task(()=>patch({color:null}));
$('resetCamera').onclick=()=>task(()=>patch({azimuth:-52,elevation:27,roll:0,zoom:1,pan_x:0,pan_y:0}));
$('saveCamera').onclick=()=>task(async()=>{const r=await api('camera',{target});$('output').textContent='视角已保存：'+r.path;});
$('loadCamera').onclick=()=>{const path=prompt('camera.json 本机路径');if(path)task(async()=>{await api('camera',{target,path,load:true});geometryCache.delete(target);await render();});};
$('openData').onclick=()=>$('dataDialog').showModal();
$('setup').onclick=()=>task(async()=>{
  const methods=$('paths').value.split('\n').map(s=>s.trim()).filter(Boolean).map(line=>{const p=line.indexOf('|');if(p<1)throw new Error('每行格式为 方法名 | 目录');return {name:line.slice(0,p).trim(),directory:line.slice(p+1).trim()};});
  const targets=$('targets').value.split(',').map(t=>t.trim()).filter(Boolean);
  state=await api('setup',{methods,targets:targets.length?targets:null});geometryCache.clear();target=state.targets[0];$('dataDialog').close();controls();await render();
  if(state.warnings.length)$('output').textContent=state.warnings.join('\n');
});
$('demo').onclick=()=>task(async()=>{state=await api('demo');geometryCache.clear();target=state.targets[0];controls();await render();});
$('saveSession').onclick=()=>{const path=prompt('另存会话 JSON 路径（留空保存默认会话）','');if(path!==null)task(async()=>{const r=await api('save',{path});$('output').textContent='会话已保存：'+r.path;});};
$('loadSession').onclick=()=>{const path=prompt('会话 JSON 本机路径');if(path)task(async()=>{state=await api('load',{path});geometryCache.clear();target=state.targets[0];controls();await render();});};
$('export').onclick=()=>$('exportDialog').showModal();
$('doExport').onclick=()=>task(async()=>{
  $('dismissProgress')?.remove();
  $('exportDialog').close();document.body.classList.add('exporting');$('exportProgress').hidden=false;$('progressBar').value=0;$('progressText').textContent='开始导出';$('progressDetail').textContent='';
  try {
    const job=await api('export',{size:+$('exportSize').value,cell:+$('cellSize').value,pdf:$('pdf').checked,comparison:$('comparison').checked});
    let info;
    do {
      const response=await fetch('/api/jobs/'+job.job_id);info=await response.json();
      if(!response.ok||info.state==='failed')throw new Error(info.message||info.error);
      $('progressBar').value=info.percent||0;$('progressText').textContent=`${info.percent||0}% · ${info.message}`;
      $('progressDetail').textContent=info.completed===undefined?'':`${info.completed} / ${info.total} 步骤`;
      if(info.state!=='complete')await new Promise(resolve=>setTimeout(resolve,500));
    }while(info.state!=='complete');
    const r=info.result;$('progressDetail').textContent='已保存到：'+r.directory;
    let dismiss=$('dismissProgress');
    if(!dismiss){dismiss=element('button','收起进度');dismiss.id='dismissProgress';dismiss.onclick=()=>{$('exportProgress').hidden=true;};$('exportProgress').append(dismiss);}
    $('output').replaceChildren(element('p','已导出 '+r.file_count+' 组独立图像：'+r.directory));
    for(const [label,url] of [['浏览 PDF / JPG 素材',r.index],['下载全部 ZIP',r.zip]]){const a=element('a',label+' ↗  ');a.href=url;a.target='_blank';a.rel='noopener';$('output').append(a);}
    $('output').scrollIntoView({behavior:'smooth',block:'center'});
    return '导出完成 · '+r.directory;
  }catch(e){$('progressText').textContent='导出失败';$('progressDetail').textContent=e.message;throw e;}
  finally{document.body.classList.remove('exporting');}
});
task(async()=>{state=await (await fetch('/api/state')).json();$('hint').textContent='实时拖动旋转；滚轮缩放，松开恢复高清效果。';if(state.export_settings){$('exportSize').value=state.export_settings.size;$('cellSize').value=state.export_settings.cell;$('pdf').checked=state.export_settings.pdf;$('comparison').checked=state.export_settings.comparison;}if(state.targets.length){target=state.targets[0];controls();await render();}});
