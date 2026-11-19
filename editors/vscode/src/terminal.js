'use strict';
/**
 * The command lines the extension's commands type into the integrated terminal (compile, run,
 * publish) and the folder `aip get` writes for the import command. No `vscode` import, so node
 * tests it. The terminal's shell is the user's, so a word is quoted only when it must be, with
 * double quotes, which bash, zsh, fish, PowerShell and cmd all read; inputs for a run go through a
 * file (`-i @path`) rather than JSON on the command line, which no one quoting suits every shell.
 */

const path = require('node:path');
const { splitCommand } = require('./compiler');

/** A word as a shell reads it: bare when it is plain, in double quotes otherwise. */
function quote(word) {
  const text = String(word);
  if (/^[A-Za-z0-9_@%+=:,./\\-]+$/.test(text)) return text;
  return `"${text.replace(/(["\\$`])/g, '\\$1')}"`;
}

/** The `aip.command` setting's words, then `args`, as one line. */
function commandLine(command, args) {
  return [...splitCommand(command), ...args].map(quote).join(' ');
}

/** `aip compile <folder>`: check it and write its bundle beside it. */
const compileLine = (command, folder) => commandLine(command, ['compile', folder]);

/** `aip run <folder> -i @<inputs file>`. */
const runLine = (command, folder, inputsFile) => commandLine(command, ['run', folder, ...(inputsFile ? ['-i', `@${inputsFile}`] : [])]);

/** `aip publish <folder>`: compile and upload it under its name. */
const publishLine = (command, folder) => commandLine(command, ['publish', folder]);

/** Where `aip get ref --out` writes under `parent`: a folder named after the name, without `@rev`. */
function importFolder(parent, ref) {
  const name = String(ref).trim().split('@')[0];
  return path.join(parent, name);
}

/** The Start step's inputs as a JSON template for the run command: `{"message": ""}`, every
 * declared input with an empty value of its type, from the graph of the last compile. */
function inputsTemplate(graph) {
  if (!graph || !Array.isArray(graph.nodes)) return {};
  const start = graph.nodes.find((n) => n.labels.includes('Step') && n.properties.kind === 'Start');
  if (!start) return {};
  const keys = new Set((graph.edges || []).filter((e) => e.type === 'PRODUCES' && e.start === start.id).map((e) => e.end));
  const empty = { string: '', integer: 0, float: 0, boolean: false, true_or_false: false, list: [], object: {} };
  const template = {};
  for (const node of graph.nodes) {
    if (!keys.has(node.id)) continue;
    const name = node.properties.name;
    const type = String(node.properties.type || 'string').split(/[\s[]/)[0];
    template[name] = Object.prototype.hasOwnProperty.call(empty, type) ? empty[type] : '';
  }
  return template;
}

module.exports = { quote, commandLine, compileLine, runLine, publishLine, importFolder, inputsTemplate };
