const fs = require('node:fs');
const assert = require('node:assert/strict');
const yaml = require('../../node_modules/js-yaml');
const workflow = yaml.load(fs.readFileSync('.github/workflows/desktop-build.yml', 'utf8'));
const job = workflow.jobs['release-visual-review'];
assert(job, 'Explicit remote visual gate exists');
function selected(event, inputs = {}) {
  return !!Function('github', 'inputs', 'return (' + job.if + ')')({ event_name: event }, inputs);
}
assert(selected('workflow_dispatch'));
for (const event of ['push', 'pull_request']) assert(!selected(event));
for (const name of ['probe_only', 'probe_family', 'packaged_smoke_only', 'windows_user_fixture_only',
  'linux_packaged_smoke_only', 'release_tag']) assert(!selected('workflow_dispatch', { [name]: true }), name);
assert.equal(job.env.RELEASE_VISUAL_ALLOWED, '1');
assert.deepEqual(job.services.postgres.ports, ['127.0.0.1:5432:5432']);
assert(job.env.ONEIRODEX_CI_CONTROL_DATABASE_URL.endsWith('/oneirodex_release_visual_control_test'));
assert(job.steps.some(step => step.run?.includes('npm run build:native-spas')));
assert(job.steps.some(step => step.run?.includes('--require-hashes -r requirements.lock')));
assert(job.steps.some(step => step.run?.includes('release_visual_review.py --run')));
const upload = job.steps.find(step => step.with?.name === 'release-visual-evidence');
assert.equal(upload.if, 'always()');
assert(!/^oneirodex-(full|thin)-/.test(upload.with.name));
console.log('Release visual workflow: normal manual selection only; isolated backend; diagnostics excluded from installers.');
