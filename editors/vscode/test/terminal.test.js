'use strict';
// The command lines the extension types into the terminal, and the folder an import writes.

const path = require('node:path');
const { test } = require('node:test');
const assert = require('node:assert/strict');

const { quote, compileLine, runLine, publishLine, importFolder, inputsTemplate } = require('../src/terminal');

test('a plain word is bare, anything else in double quotes', () => {
  assert.equal(quote('/a/b-c/d_e.json'), '/a/b-c/d_e.json');
  assert.equal(quote('@/tmp/x.json'), '@/tmp/x.json');
  assert.equal(quote('/a b/c'), '"/a b/c"');
  assert.equal(quote('say "$hi"'), '"say \\"\\$hi\\""');
});

test('compile, run and publish lines use the aip.command setting\'s words', () => {
  assert.equal(compileLine('aip', '/w/billing-support'), 'aip compile /w/billing-support');
  assert.equal(compileLine('uv run aip', '/my procs/x'), 'uv run aip compile "/my procs/x"');
  assert.equal(publishLine('"/opt/my tools/aip"', '/w/x'), '"/opt/my tools/aip" publish /w/x');
  assert.equal(runLine('aip', '/w/x', '/tmp/aip-inputs-x.json'), 'aip run /w/x -i @/tmp/aip-inputs-x.json');
  assert.equal(runLine('aip', '/w/x'), 'aip run /w/x');
});

test('an import writes a folder named after the name, without the revision', () => {
  assert.equal(importFolder('/w', 'billing_support@3'), path.join('/w', 'billing_support'));
  assert.equal(importFolder('/w', ' make_procedure '), path.join('/w', 'make_procedure'));
});

test('the run\'s inputs template has every Start input with an empty value of its type', () => {
  const graph = {
    nodes: [
      { id: 'step:start', labels: ['Step', 'Start'], properties: { name: 'start', kind: 'Start' } },
      { id: 'data:message', labels: ['Data'], properties: { name: 'message', type: 'string' } },
      { id: 'data:count', labels: ['Data'], properties: { name: 'count', type: 'integer' } },
      { id: 'data:tone', labels: ['Data'], properties: { name: 'tone', type: 'choice' } },
      { id: 'data:later', labels: ['Data'], properties: { name: 'later', type: 'string' } },
    ],
    edges: [
      { type: 'PRODUCES', start: 'step:start', end: 'data:message', properties: {} },
      { type: 'PRODUCES', start: 'step:start', end: 'data:count', properties: {} },
      { type: 'PRODUCES', start: 'step:start', end: 'data:tone', properties: {} },
      { type: 'PRODUCES', start: 'step:other', end: 'data:later', properties: {} },
    ],
  };
  assert.deepEqual(inputsTemplate(graph), { message: '', count: 0, tone: '' });
  assert.deepEqual(inputsTemplate(null), {});
});
