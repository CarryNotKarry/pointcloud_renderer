// Mathematical camera regression checks; Node is needed only for this dev test.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const context=vm.createContext({Map,Math});
vm.runInContext(fs.readFileSync(__dirname+'/workbench_web/live.js','utf8'),context);
const result=vm.runInContext(`(()=>{
  const camera={position:[2,-3,1],focal_point:[0,0,0],view_up:[0,0,1],parallel_scale:.8};
  const identity=orbitCamera(camera,0,0);
  const rotated=orbitCamera(camera,.2,.1);
  return {identity,rotated,original:camera};
})()`,context);
assert.ok(Math.abs(Math.hypot(...result.rotated.position)-Math.hypot(...result.original.position))<1e-12);
assert.equal(result.rotated.parallel_scale,.8);
assert.ok(result.identity.position.every((v,i)=>Math.abs(v-result.original.position[i])<1e-12));
assert.equal(JSON.stringify(result.rotated.focal_point),'[0,0,0]');
assert.equal(JSON.stringify(result.original.position),'[2,-3,1]');
console.log('Live orbit preserves distance, focal point, scale and input camera.');
