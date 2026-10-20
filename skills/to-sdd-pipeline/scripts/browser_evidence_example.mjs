#!/usr/bin/env node
/**
 * Optional executable prerequisite example for an already task-owned local
 * Chromium CDP endpoint. Does not launch/terminate the browser or delete profiles.
 * The owning managed producer must close that process and verify cleanup.
 */
import { readFile, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { isAbsolute, dirname, join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { probeRuntime, probeNativeTime, probeVisibility } from './browser_evidence_probe.mjs';

const help = `Usage:
  node browser_evidence_example.mjs --playwright-entry /absolute/package/index.mjs
    --owned-endpoint http://127.0.0.1:PORT --runtime-only
  node browser_evidence_example.mjs --playwright-entry /absolute/package/index.mjs
    --owned-endpoint http://127.0.0.1:PORT --url AUTHORIZED_URL
    --expected /absolute/runtime.json --output /absolute/output/probes.json

Use an existing Playwright >=1.60 package. No dependency installation is performed.
The runtime-only mode writes JSON to stdout for sdd_history.py observe-runtime.
The full mode preserves probe results and closes only the pages/contexts it creates.
The endpoint must belong to a fresh task browser whose default context has never
used time emulation. The expected file must retain browser, automation and node.
The parent owns final browser process exit, profile cleanup, and evidence settlement.
`;

async function main() {
  if (process.argv.includes('--help')) {
    process.stdout.write(help);
    return;
  }
  const options = {};
  for (let index = 2; index < process.argv.length; index += 1) {
    const key = process.argv[index];
    if (key === '--runtime-only') options[key] = true;
    else if (['--playwright-entry', '--owned-endpoint', '--url', '--expected', '--output'].includes(key)) {
      options[key] = process.argv[++index];
    } else throw new Error(`unknown argument: ${key}`);
  }
  const entry = options['--playwright-entry'];
  if (!entry || !isAbsolute(entry)) throw new Error('--playwright-entry must be an absolute existing module path');
  const endpoint = new URL(options['--owned-endpoint']);
  if (!['127.0.0.1', 'localhost', '[::1]'].includes(endpoint.hostname) ||
      !['http:', 'https:', 'ws:', 'wss:'].includes(endpoint.protocol)) {
    throw new Error('example supports a task-owned local CDP endpoint only');
  }
  if (!options['--runtime-only'] &&
      (!options['--url'] || !isAbsolute(options['--expected'] ?? '') ||
       !isAbsolute(options['--output'] ?? ''))) {
    throw new Error('full mode requires --url and absolute --expected and --output paths');
  }
  // The selected entry and package.json must be in the same installed package.
  const require = createRequire(pathToFileURL(entry));
  const packageInfo = require(join(dirname(entry), 'package.json'));
  const [major, minor] = packageInfo.version.split('.').map(Number);
  if (!(major > 1 || (major === 1 && minor >= 60))) {
    throw new Error('this CDP example requires Playwright >=1.60 for noDefaults');
  }
  const { chromium } = await import(pathToFileURL(entry));
  let browser, fixture, native, background;
  const report = { version: 1, kind: 'browser-prerequisites', checks: {}, cleanup: [] };
  const readRuntime = () => ({
    browser: browser.version(), automation: packageInfo.version, node: process.version,
  });
  try {
    browser = await chromium.connectOverCDP(endpoint.href, { noDefaults: true, timeout: 10000 });
    if (options['--runtime-only']) {
      process.stdout.write(`${JSON.stringify(readRuntime())}\n`);
      return;
    }
    const expected = JSON.parse(await readFile(options['--expected'], 'utf8'));
    if (!expected || !['browser', 'automation', 'node'].every(key =>
      typeof expected[key] === 'string' && expected[key])) {
      throw new Error('expected must preserve captured browser, automation and node identities');
    }
    report.checks.runtime = await probeRuntime({ readRuntime, expected });
    if (report.checks.runtime.result !== 'passed') throw new Error('runtime changed; capture continuation before testing');
    fixture = await browser.newContext();
    const fixturePage = await fixture.newPage();
    await fixturePage.clock.setFixedTime(0);
    report.fixtureEpoch = await fixturePage.evaluate(() => Date.now());
    // noDefaults applies to the existing default context, not new contexts.
    const defaultContext = browser.contexts().find(context => context !== fixture);
    if (!defaultContext) throw new Error('task-owned browser has no default context');
    native = await defaultContext.newPage();
    background = await defaultContext.newPage();
    await native.goto(options['--url'], { waitUntil: 'load', timeout: 10000 });
    await native.bringToFront();
    report.checks.time = await probeNativeTime({
      readBrowserTime: () => native.evaluate(() => Date.now()),
      intervalMs: 100, clockSkewMs: 0,
    });
    if (report.checks.time.result !== 'passed') throw new Error('native time prerequisite failed');
    await native.evaluate(() => {
      window.__sddVisibilityProbe = [];
      document.addEventListener('visibilitychange', event => {
        window.__sddVisibilityProbe.push({
          state: document.visibilityState, trusted: event.isTrusted,
          monotonicMs: performance.now(),
        });
      });
    });
    report.checks.visibility = await probeVisibility({
      read: () => native.evaluate(() => ({
        state: document.visibilityState, events: window.__sddVisibilityProbe,
      })),
      hide: () => background.bringToFront(), show: () => native.bringToFront(),
      timeoutMs: 3000, hiddenForMs: 100,
    });
  } catch (error) {
    report.error = String(error.message ?? error);
    process.exitCode = 1;
  } finally {
    for (const [name, resource] of [['native-page', native], ['background-page', background],
      ['fixture-context', fixture], ['connection', browser]]) {
      if (!resource) continue;
      try {
        await resource.close();
        report.cleanup.push({ name, result: 'closed' });
      } catch (error) {
        report.cleanup.push({ name, result: 'failed', error: String(error.message ?? error) });
        process.exitCode = 1;
      }
    }
    if (!options['--runtime-only']) {
      report.result = !report.error && report.cleanup.every(item => item.result === 'closed') &&
        Object.keys(report.checks).length === 3 &&
        Object.values(report.checks).every(check => check.result === 'passed') ? 'passed' : 'failed';
      if (report.result !== 'passed') process.exitCode = 1;
      await writeFile(options['--output'], `${JSON.stringify(report, null, 2)}\n`, { flag: 'wx' });
    }
  }
}

main().catch(error => {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
});
