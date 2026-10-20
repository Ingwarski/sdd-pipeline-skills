import assert from 'node:assert/strict';
import test from 'node:test';
import {
  probeRuntime, probeNativeTime, probeVisibility,
} from '../skills/to-sdd-pipeline/scripts/browser_evidence_probe.mjs';

test('runtime probe reads actual browser and rejects changed or missing identities', async () => {
  const expected = { browser: 'Browser/1', automation: 'Adapter/1' };
  assert.equal((await probeRuntime({ readRuntime: async () => expected, expected })).result, 'passed');
  const changed = await probeRuntime({
    readRuntime: async () => ({ browser: 'Browser/2' }), expected,
  });
  assert.equal(changed.result, 'failed');
  assert.equal(changed.failures.length, 2);
  assert.equal(changed.observations.actual.browser, 'Browser/2');
});

function timeAdapter(read) {
  let host = 1000;
  return {
    hostNow: () => host, wait: async ms => { host += ms; },
    readBrowserTime: async () => read(host), intervalMs: 100,
  };
}

test('native time requires advancement and host-bracket agreement', async () => {
  assert.equal((await probeNativeTime(timeAdapter(host => host))).result, 'passed');
  const frozen = await probeNativeTime(timeAdapter(() => 1000));
  assert.equal(frozen.result, 'failed');
  assert.equal(frozen.observations.length, 3);
  assert.ok(frozen.failures.some(value => value.includes('did not both advance')));
  const fastFixture = await probeNativeTime(timeAdapter(host => 1000 + 2 * (host - 1000)));
  assert.equal(fastFixture.result, 'failed');
  assert.ok(fastFixture.failures.some(value => value.includes('host bracket')));
});

test('clock skew is explicit and does not replace advancement', async () => {
  const adapter = () => timeAdapter(host => host + 5);
  assert.equal((await probeNativeTime(adapter())).result, 'failed');
  assert.equal((await probeNativeTime({ ...adapter(), clockSkewMs: 5 })).result, 'passed');
  assert.equal((await probeNativeTime({
    ...timeAdapter(() => 1000), clockSkewMs: 1000,
  })).result, 'failed');
});

test('invalid or backwards time is failed evidence', async () => {
  assert.equal((await probeNativeTime(timeAdapter(() => NaN))).result, 'failed');
  let sample = 1000;
  const report = await probeNativeTime({
    readBrowserTime: async () => sample, hostNow: () => --sample,
    wait: async () => {}, intervalMs: 1,
  });
  assert.equal(report.result, 'failed');
});

function visibilityAdapter({ fake = false, noHide = false, interrupted = false } = {}) {
  let now = 0, state = 'visible', shows = 0;
  const events = [];
  const change = next => {
    state = next;
    events.push({ state, trusted: !fake, monotonicMs: now });
  };
  return {
    options: {
      read: async () => ({ state, events: [...events] }),
      hide: async () => { if (!noHide) change('hidden'); },
      show: async () => { shows++; change('visible'); },
      wait: async ms => {
        now += ms;
        if (interrupted && state === 'hidden') {
          change('visible');
          change('hidden');
        }
      },
      monotonicNow: () => now, timeoutMs: 50, hiddenForMs: 100, pollMs: 10,
    },
    shows: () => shows,
  };
}

test('visibility requires actual hidden and visible states and trusted event sequence', async () => {
  const adapter = visibilityAdapter();
  const report = await probeVisibility(adapter.options);
  assert.equal(report.result, 'passed');
  assert.deepEqual(report.observations.map(value => value.state), [
    'visible', 'hidden', 'hidden', 'visible',
  ]);
  assert.equal(adapter.shows(), 1);
});

test('background action that stays visible fails and still restores', async () => {
  const adapter = visibilityAdapter({ noHide: true });
  const report = await probeVisibility(adapter.options);
  assert.equal(report.result, 'failed');
  assert.ok(report.failures.some(value => value.includes('hidden state was not observed')));
  assert.equal(adapter.shows(), 1);
});

test('synthetic events and interrupted hidden interval cannot pass', async () => {
  for (const settings of [{ fake: true }, { interrupted: true }]) {
    const report = await probeVisibility(visibilityAdapter(settings).options);
    assert.equal(report.result, 'failed');
  }
});

test('old visibility events cannot stand in for a new transition', async () => {
  const adapter = visibilityAdapter();
  adapter.options.read = async () => ({
    state: 'visible',
    events: [
      { state: 'hidden', trusted: true, monotonicMs: -1000 },
      { state: 'visible', trusted: true, monotonicMs: -500 },
    ],
  });
  assert.equal((await probeVisibility(adapter.options)).result, 'failed');
});

test('restoration failures remain failures with original observations retained', async () => {
  const adapter = visibilityAdapter();
  adapter.options.show = async () => { throw new Error('restore failed'); };
  const report = await probeVisibility(adapter.options);
  assert.equal(report.result, 'failed');
  assert.ok(report.failures.includes('restore failed'));
  assert.equal(report.observations.length, 3);
});
