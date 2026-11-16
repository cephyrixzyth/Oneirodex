import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const scriptPath = path.join(ROOT, 'oneirodex', 'setup', 'default_theme', 'js', 'library_slideshow.js');
const script = fs.readFileSync(scriptPath, 'utf8');

test('library screenshot hover renders game and provider data as text', async () => {
  const dom = new JSDOM(
    '<div id="details-game-1" class="popup-game-details hidden"></div>' +
      '<div class="game-card" data-uuid="game-1"><img class="game-cover"></div>',
    { runScripts: 'outside-only', url: 'http://oneirodex.test/' },
  );
  const { window } = dom;
  const timers = new Map();
  let nextTimerId = 0;
  window.setTimeout = (callback) => {
    const id = ++nextTimerId;
    timers.set(id, callback);
    return id;
  };
  window.clearTimeout = (id) => timers.delete(id);
  window.$ = () => ({ is: () => true });
  window.fetch = async () => ({
    ok: true,
    json: async () => ['https://images.example/cover.jpg"><svg onload=alert(3)>'],
  });

  const card = window.document.querySelector('.game-card');
  card.dataset.name = '<img src=x onerror=alert(1)>';
  card.dataset.size = '"><svg onload=alert(2)>';
  card.dataset.genres = '<script>alert(4)</script>, Puzzle';
  window.gameCard = card;
  window.eval(script);
  window.showDetails(card, 'game-1');

  assert.equal(timers.size, 1, 'debounced render is queued');
  const render = timers.values().next().value;
  timers.clear();
  render();
  for (let attempt = 0; attempt < 5; attempt += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }

  const details = window.document.getElementById('details-game-1');
  assert.equal(details.querySelector('.game-name').textContent, card.dataset.name);
  assert.equal(details.querySelector('.game-size').textContent, card.dataset.size);
  const genreChips = details.querySelectorAll('.game-info-box > div:last-child .chip');
  assert.equal(genreChips[0].textContent, '<script>alert(4)</script>');
  assert.equal(genreChips[1].textContent, 'Puzzle');
  assert.equal(details.querySelectorAll('img').length, 1, 'only the screenshot image is rendered');
  assert.equal(details.querySelector('svg, script, [onerror], [onload]'), null);

  dom.window.close();
});
