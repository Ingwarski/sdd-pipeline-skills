/**
 * Optional browser-adapter probes. No browser launch, dependencies, acceptance,
 * filesystem cleanup, or history mutation. Callbacks read the actual test page.
 */
import { setTimeout as delay } from 'node:timers/promises';

const result = (observations, failures) => ({
  result: failures.length ? 'failed' : 'passed', observations, failures,
});

function positive(value, name) {
  if (!Number.isFinite(value) || value <= 0) throw new Error(`${name} must be positive`);
}

/** Read the attached runtime, comparing every recorded identity exactly. */
export async function probeRuntime({ readRuntime, expected }) {
  if (!expected || Object.keys(expected).length === 0 ||
      Object.values(expected).some(value => typeof value !== 'string' || !value)) {
    throw new Error('expected must contain nonempty string runtime identities');
  }
  const actual = await readRuntime();
  const failures = Object.entries(expected)
    .filter(([key, value]) => actual?.[key] !== value)
    .map(([key]) => `runtime identity differs: ${key}`);
  return result({ expected: { ...expected }, actual }, failures);
}

/**
 * Same-host consistency probe, not proof of native provenance. Keep emulation
 * in a separate context. The caller supplies any justified clock-skew allowance.
 */
export async function probeNativeTime({
  readBrowserTime, intervalMs, clockSkewMs = 0, samples = 3,
  hostNow = Date.now, wait = delay,
}) {
  positive(intervalMs, 'intervalMs');
  if (!Number.isInteger(samples) || samples < 2 || samples > 100) {
    throw new Error('samples must be an integer between 2 and 100');
  }
  if (!Number.isFinite(clockSkewMs) || clockSkewMs < 0) {
    throw new Error('clockSkewMs must be finite and nonnegative');
  }
  const observations = [];
  const failures = [];
  for (let index = 0; index < samples; index += 1) {
    if (index) await wait(intervalMs);
    const hostBefore = hostNow();
    const browserTime = await readBrowserTime();
    const hostAfter = hostNow();
    observations.push({ hostBefore, browserTime, hostAfter });
    if (![hostBefore, browserTime, hostAfter].every(Number.isFinite) ||
        hostAfter < hostBefore ||
        browserTime < hostBefore - clockSkewMs ||
        browserTime > hostAfter + clockSkewMs) {
      failures.push(`sample ${index}: browser time is outside the host bracket`);
    }
    if (index && (browserTime <= observations[index - 1].browserTime ||
        hostBefore <= observations[index - 1].hostAfter)) {
      failures.push(`sample ${index}: browser and host time did not both advance`);
    }
  }
  return { ...result(observations, failures), intervalMs, clockSkewMs };
}

/**
 * `read` returns {state, events:[{state, trusted, monotonicMs}]} from one page.
 * Install the real visibilitychange listener before calling. `hide` and `show`
 * perform real platform actions; never dispatch events or overwrite visibility.
 * Callback operations must themselves have finite tool/producer timeouts.
 */
export async function probeVisibility({
  read, hide, show, timeoutMs, hiddenForMs, pollMs = 25,
  monotonicNow = () => performance.now(), wait = delay,
}) {
  for (const [name, value] of Object.entries({ timeoutMs, hiddenForMs, pollMs })) {
    positive(value, name);
  }
  const observations = [];
  const failures = [];
  const snapshot = async () => {
    const value = await read();
    observations.push({ hostMonotonicMs: monotonicNow(), ...structuredClone(value) });
    if (!['hidden', 'visible'].includes(value?.state) || !Array.isArray(value.events)) {
      throw new Error('visibility adapter must return actual state and event list');
    }
    return value;
  };
  const until = async state => {
    const started = monotonicNow();
    while (true) {
      const value = await snapshot();
      if (value.state === state) return value;
      if (monotonicNow() - started >= timeoutMs) {
        throw new Error(`required ${state} state was not observed`);
      }
      await wait(pollMs);
    }
  };
  let initial, hidden, held, visible;
  try {
    initial = await snapshot();
    if (initial.state !== 'visible') throw new Error('initial page must be observed visible');
    await hide();
    hidden = await until('hidden');
    await wait(hiddenForMs);
    held = await snapshot();
    if (held.state !== 'hidden') throw new Error('page did not remain hidden');
  } catch (error) {
    failures.push(String(error.message ?? error));
  } finally {
    // Restore the page even when a prerequisite or adapter fails.
    try {
      await show();
      visible = await until('visible');
    } catch (error) {
      failures.push(String(error.message ?? error));
    }
  }
  if (initial && hidden && held && visible) {
    const priorCount = initial.events.length;
    const events = visible.events.slice(priorCount);
    const hiddenIndex = events.findIndex(event => event.state === 'hidden');
    const shownIndex = events.findIndex((event, index) =>
      index > hiddenIndex && event.state === 'visible');
    if (hiddenIndex < 0 || shownIndex < 0) {
      failures.push('missing real hidden -> visible event sequence');
    } else {
      const hiddenEvent = events[hiddenIndex];
      const shownEvent = events[shownIndex];
      if (hiddenEvent.trusted !== true || shownEvent.trusted !== true ||
          !Number.isFinite(hiddenEvent.monotonicMs) ||
          !Number.isFinite(shownEvent.monotonicMs) ||
          shownEvent.monotonicMs - hiddenEvent.monotonicMs < hiddenForMs) {
        failures.push('untrusted, invalid, or too-short visibility transition');
      }
      const duringHold = held.events.slice(priorCount + hiddenIndex + 1);
      if (duringHold.some(event => event.state !== 'hidden')) {
        failures.push('hidden interval was interrupted before restoration');
      }
    }
  }
  return { ...result(observations, failures), hiddenForMs, timeoutMs };
}
