const fs = require('node:fs');
const assert = require('node:assert/strict');
const yaml = require('../../node_modules/js-yaml');
const workflow = yaml.load(fs.readFileSync('.github/workflows/docker-publish.yml', 'utf8'));
assert.equal(workflow.on.workflow_dispatch.inputs.preflight_only.default, false);
const preflight = workflow.jobs['image-preflight'];
assert.deepEqual(preflight.permissions, { contents: 'read' });
assert.equal(preflight.environment, undefined, 'Preflight cannot access release environment credentials');
function selected(name, event, input, main = false) {
  const github = { event_name: event, ref: main ? 'refs/heads/main' : 'refs/heads/feat/theme-art',
    event: { repository: { default_branch: 'main' } } };
  return !!Function('github', 'inputs', 'format', 'return (' + workflow.jobs[name].if + ')')(
    github, { preflight_only: input }, (pattern, value) => pattern.replace('{0}', value));
}
for (const main of [false, true]) {
  assert(selected('image-preflight', 'workflow_dispatch', true, main));
  assert(!selected('tests', 'workflow_dispatch', true, main));
  assert(!selected('publish', 'workflow_dispatch', true, main));
  assert(!selected('image-preflight', 'workflow_dispatch', false, main));
  assert(selected('tests', 'workflow_dispatch', false, main));
  assert.equal(selected('publish', 'workflow_dispatch', false, main), main);
}
assert(!selected('image-preflight', 'push', false));
assert(selected('tests', 'push', false));
assert(selected('publish', 'push', false));
const builds = preflight.steps.filter(step => (step.uses || '').startsWith('docker/build-push-action@'));
assert.equal(builds.length, 2);
assert(builds.every(step => step.with.push === false));
assert(builds.some(step => step.with.platforms === 'linux/amd64,linux/arm64' && step.with.outputs === 'type=cacheonly'));
assert(builds.some(step => step.with.platforms === 'linux/amd64' && step.with.load === true));
assert(!preflight.steps.some(step => /login-action|secrets\./.test(JSON.stringify(step))));
assert(preflight.steps.some(step => step.run?.includes('docker_release_preflight.sh')));
console.log('Docker preflight: explicit manual mode only; tests/publish isolated; both architectures; no registry write or release credentials.');
