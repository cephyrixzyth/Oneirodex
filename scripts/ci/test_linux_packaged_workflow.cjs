const fs = require('node:fs');
const cp = require('node:child_process');
const assert = require('node:assert/strict');
const yaml = require('../../node_modules/js-yaml');
const file = '.github/workflows/desktop-build.yml';
const base = yaml.load(cp.execFileSync('git',['show','0dc15da0510b2529a26b9a4e43a372841e75db62:'+file],{encoding:'utf8'}));
const current = yaml.load(fs.readFileSync(file,'utf8'));
assert.equal(current.on.workflow_dispatch.inputs.linux_packaged_smoke_only?.default,false);
assert.deepEqual(current.permissions,base.permissions);
for(const event of ['push','pull_request']) assert.deepEqual(current.on[event],base.on[event]);
for(const name of Object.keys(base.jobs)) {
  const before={...base.jobs[name]}, after={...current.jobs[name]};
  delete before.if;delete after.if;
  assert.deepEqual(after,before,'Existing job steps/permissions preserved: '+name);
}
for(const [name,value] of Object.entries(base.on.workflow_dispatch.inputs)) {
  const before={...value},after={...current.on.workflow_dispatch.inputs[name]};
  if(['package_source_run','package_archive_digest'].includes(name)) {
    delete before.description;delete after.description;
    assert(current.on.workflow_dispatch.inputs[name].description.includes('selected platform'));
  }
  assert.deepEqual(after,before,'Existing input contract preserved: '+name);
}
function selected(job,event,inputs={},tag=false) {
 const github={event_name:event,ref_type:tag?'tag':'branch',ref_name:tag?'v1.1.9':'codex/release-v1.1.9',
  ref:tag?'refs/tags/v1.1.9':'refs/heads/codex/release-v1.1.9',event:{repository:{default_branch:'main'}}};
 const format=(pattern,value)=>pattern.replace('{0}',value);
 return !!Function('github','inputs','format','return ('+current.jobs[job].if+')')(github,inputs,format);
}
const names=['macos-coalition-probe','rust-checks','build','windows-packaged-probe','linux-packaged-probe','release'];
const cases=[
 ['push',{},false,[1,1,1,0,0,0]],['pull_request',{},false,[1,1,1,0,0,0]],
 ['push',{},true,[1,1,1,0,0,1]],['workflow_dispatch',{},false,[1,1,1,0,0,0]],
 ['workflow_dispatch',{probe_only:true},false,[1,0,0,0,0,0]],
 ['workflow_dispatch',{windows_user_fixture_only:true},false,[0,0,0,1,0,0]],
 ['workflow_dispatch',{packaged_smoke_only:true},false,[0,0,0,1,0,0]],
 ...[{}, {packaged_smoke_only:true},{windows_user_fixture_only:true},{probe_only:true},{probe_family:true},
     {release_tag:'v1.1.9'}].map(extra=>['workflow_dispatch',{linux_packaged_smoke_only:true,...extra},false,[0,0,0,0,1,0]])
];
for(const [event,inputs,tag,expected] of cases)
 assert.deepEqual(names.map(name=>Number(selected(name,event,inputs,tag))),expected,JSON.stringify({event,inputs,tag}));
const job=current.jobs['linux-packaged-probe'];
assert.equal(job['runs-on'],'ubuntu-22.04');
assert.deepEqual(job.permissions,{contents:'read',actions:'read'});
assert(job.steps.some(s=>s.run?.includes('test_linux_*.py')));
assert(job.steps.some(s=>s.run?.includes('--version \'=2.1.0\' --locked')));
const run=job.steps.find(s=>s.name==='Install and exercise the pinned Linux package');
assert(run.run.includes('probe_linux_packaged.py --execute --connected'));
assert(!job.steps.some(s=>/tauri build|cargo build/.test(s.run||'')));
assert(job.steps.some(s=>s.run?.includes('npm run build:native-spas')));
assert(job.steps.some(s=>s.with?.['node-version']==='22'));
assert(job.steps.some(s=>s.run?.includes('--require-hashes -r requirements.lock')));
assert(job.steps.some(s=>s.run?.includes('unittest discover -s tests -p test_native_companion_cors.py')));
assert(job.steps.some(s=>s.run?.includes('unittest discover -s tests -p test_native_bearer_denial.py')));
assert.deepEqual(job.services.postgres.ports,['127.0.0.1:5432:5432']);
const linuxPackages=job.steps.find(s=>s.name==='Install native Linux test prerequisites').run;
assert(linuxPackages.includes('native_thunar_version'));
assert(linuxPackages.includes('native_xfconf_version'));
assert(linuxPackages.includes('xdotool xclip xdg-utils x11-utils'));
console.log(JSON.stringify({parsed:true,contexts:cases.length,original_job_steps_and_inputs_preserved:true,immutable_desktop_package:true,real_server_and_provider:true}));
