// The training desk. It reads three endpoints and draws what they say; it changes nothing.
// Every value from the desk is placed with textContent, so nothing in a training's files or
// its record can ever be read as markup.
'use strict';

const STATUSES = ['approved', 'draft', 'stale', 'not-started', 'skipped', 'unavailable'];
const PIPELINE = ['intake', 'research-plan', 'research', 'blueprint', 'document', 'brief', 'deck'];
const WIDE = window.matchMedia('(min-width: 62rem)');
const NOTICES = {
  stopped: 'The desk has stopped, so this page can no longer read anything. '
    + 'Ask your assistant to open the desk again.',
  refused: 'This link is not the one the running desk gave out. '
    + 'Ask your assistant to open the desk again and use the link it gives you, whole.',
};
const view = { token: '', trainings: [], open: null, shown: null, pushed: 0, readAt: 0, preview: 0 };

const byId = (id) => document.getElementById(id);

// --- small builders ---------------------------------------------------------------

function make(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function add(parent, ...children) {
  for (const child of children) {
    if (child) parent.append(child);
  }
  return parent;
}

function words(count, one, many) {
  return count + ' ' + (count === 1 ? one : many);
}

function list(value) {
  return Array.isArray(value) ? value : [];
}

function ago(then) {
  const minutes = Math.round((Date.now() - then) / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return words(minutes, 'minute', 'minutes') + ' ago';
  const hours = Math.round(minutes / 60);
  if (hours < 24) return words(hours, 'hour', 'hours') + ' ago';
  const days = Math.round(hours / 24);
  if (days < 30) return words(days, 'day', 'days') + ' ago';
  return new Date(then).toLocaleDateString(undefined,
    { year: 'numeric', month: 'short', day: 'numeric' });
}

function when(stamp) {
  const then = Date.parse(stamp);
  if (Number.isNaN(then)) return make('span', 'quiet', 'not recorded');
  const node = make('time', '', ago(then));
  node.dateTime = new Date(then).toISOString();
  node.title = new Date(then).toLocaleString();
  return node;
}

function size(bytes) {
  if (bytes < 1024) return words(bytes, 'byte', 'bytes');
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1024 / 1024).toFixed(1) + ' MB';
}

function pathInto(node, path) {
  String(path).split('/').forEach((part, index) => {
    if (index) add(node, '/', document.createElement('wbr'));
    add(node, part);
  });
  return node;
}

function levelsText(levels) {
  return list(levels).length ? list(levels).join(' · ') : 'No levels';
}

function mark(status) {
  const node = make('span', 'mark');
  node.dataset.status = status;
  node.setAttribute('aria-hidden', 'true');
  return node;
}

function statusWord(status) {
  return add(make('span', 'status'), mark(status), make('span', '', status));
}

function badge(kind, text) {
  const node = make('span', 'badge');
  node.dataset.kind = kind;
  const shape = make('span', 'badge-mark');
  shape.setAttribute('aria-hidden', 'true');
  return add(node, shape, make('span', '', text));
}

function readiness(training) {
  if (training.error) return badge('unreadable', 'Unreadable');
  const ready = training.check ? training.check.ready : training.ready;
  return ready ? badge('ready', 'Ready') : badge('blocked', 'Not ready');
}

function field(name, value) {
  const held = typeof value === 'string' ? make('span', 'field-value', value) : value;
  return add(make('span', 'field'), make('span', 'label', name), held);
}

function section(title, count) {
  const node = make('section', 'block');
  const heading = make('h3', 'block-title', title);
  if (count) add(heading, make('span', 'count', count));
  return add(node, heading);
}

function bullets(items, className) {
  const node = make('ul', className);
  for (const item of items) node.append(make('li', '', item));
  return node;
}

// --- talking to the desk ----------------------------------------------------------

class DeskError extends Error {
  constructor(kind, message) {
    super(message);
    this.kind = kind;
  }
}

function query(params) {
  return '?' + new URLSearchParams(params).toString();
}

async function ask(endpoint) {
  let response;
  try {
    response = await fetch('/api/' + endpoint, {
      headers: { 'X-Training-Studio-Token': view.token },
      cache: 'no-store',
    });
  } catch (failure) {
    throw new DeskError('stopped', NOTICES.stopped);
  }
  let body = null;
  try {
    body = await response.json();
  } catch (failure) {
    body = null;
  }
  if (response.ok && body) return body;
  const said = body && body.error ? String(body.error) : 'The desk gave no answer this page can read.';
  throw new DeskError(response.status === 403 ? 'refused' : 'failed', said);
}

function notify(text) {
  byId('notice').textContent = text;
  byId('notice').hidden = !text;
}

// --- copying ----------------------------------------------------------------------

function copyBySelection(text) {
  const holder = make('textarea', 'offscreen');
  holder.value = text;
  holder.readOnly = true;
  document.body.append(holder);
  holder.select();
  let copied = false;
  try {
    copied = document.execCommand('copy');
  } catch (failure) {
    copied = false;
  }
  holder.remove();
  return copied;
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (failure) {
    return copyBySelection(text);
  }
}

function copyButton(label, done, text) {
  const button = make('button', 'button', label);
  button.type = 'button';
  button.addEventListener('click', async () => {
    const copied = await copy(text);
    button.textContent = copied ? done : 'Not copied: select the text instead';
    window.setTimeout(() => { button.textContent = label; }, 2400);
  });
  return button;
}

function sentenceFor(training) {
  const path = '"' + training.path + '"';
  if (training.error) {
    return 'Use training-studio to look at the training in ' + path
      + '. Its record cannot be read: ' + training.error;
  }
  return 'Use training-studio to resume the training in ' + path
    + ' and tell me what is waiting on me.';
}

// --- the list ---------------------------------------------------------------------

function strip(counts) {
  const node = make('span', 'strip');
  node.setAttribute('aria-hidden', 'true');
  for (const status of STATUSES) {
    const count = Number(counts[status]) || 0;
    if (!count) continue;
    const part = make('span', 'strip-part');
    part.dataset.status = status;
    part.style.flexGrow = String(count);
    node.append(part);
  }
  return node;
}

function tally(counts) {
  const node = make('span', 'tally');
  for (const status of STATUSES) {
    const count = Number(counts[status]) || 0;
    if (!count) continue;
    add(node, add(make('span', 'tally-item'), mark(status), make('span', '', count + ' ' + status)));
  }
  return node;
}

function entry(training) {
  const button = make('button', 'entry');
  button.type = 'button';
  button.dataset.path = training.path;
  button.addEventListener('click', () => choose(training.path));
  add(button, add(make('span', 'entry-top'),
    make('span', 'entry-title', training.title || 'Untitled'), readiness(training)));
  const fields = make('span', 'fields');
  add(fields, field('Levels', levelsText(training.levels)));
  if (training.stage) add(fields, field('Stage', String(training.stage)));
  add(fields, field('Touched', when(training.touched_at)));
  add(button, fields);
  if (training.error) {
    add(button, make('span', 'entry-error', training.error));
  } else {
    add(button, strip(training.counts || {}), tally(training.counts || {}));
    if (training.blocking) add(button, make('span', 'entry-blocking', training.blocking + ' blocking'));
  }
  add(button, pathInto(make('span', 'path'), training.path));
  return add(make('li'), button);
}

function markCurrent() {
  for (const button of byId('trainings').querySelectorAll('.entry')) {
    if (button.dataset.path === view.open) button.setAttribute('aria-current', 'true');
    else button.removeAttribute('aria-current');
  }
}

function drawList() {
  const entries = view.trainings.map(entry);
  byId('trainings').replaceChildren(...entries);
  byId('empty').hidden = entries.length > 0;
  byId('count').textContent = entries.length ? String(entries.length) : '';
  markCurrent();
}

// --- one training -----------------------------------------------------------------

function cell(className, label, ...children) {
  return add(make('div', 'cell ' + className), make('p', 'label', label), ...children);
}

function titleBlock(training) {
  const status = training.status;
  const check = training.check;
  const block = make('header', 'titleblock');
  add(block, cell('cell-title', 'Training', make('h2', 'sheet-title', training.title || 'Untitled')));
  const ready = cell('cell-ready', 'Readiness', readiness(training));
  if (check) {
    const blocking = list(check.blocking).length;
    const limits = list(check.limitations).length;
    add(ready, make('p', 'cell-note', (blocking ? blocking + ' blocking' : 'Nothing blocking')
      + (limits ? ', ' + words(limits, 'limitation', 'limitations') : '')));
  }
  add(block, ready);
  if (status && check) {
    const stage = status.level ? status.stage + ' · level ' + status.level : status.stage;
    const failing = list(check.checks).length;
    add(block,
      cell('cell-field', 'Levels', make('p', 'cell-value', levelsText(status.levels))),
      cell('cell-field', 'Stage', make('p', 'cell-value', stage)),
      cell('cell-field', 'Touched', add(make('p', 'cell-value'), when(training.touched_at))),
      cell('cell-field', 'Checks', make('p', 'cell-value', check.passed + ' passed'
        + (failing ? ', ' + failing + ' not' : ''))));
    if (status.next_step) {
      add(block, cell('cell-wide', 'Next step', make('p', 'cell-value', status.next_step)));
    }
    if (status.pending_question) {
      add(block, cell('cell-wide cell-waiting', 'Waiting on you',
        make('p', 'cell-value', status.pending_question)));
    }
  } else {
    add(block, cell('cell-wide cell-waiting', 'Its record cannot be read',
      make('p', 'cell-value', training.error),
      make('p', 'cell-note', 'Nothing else about this training can be shown until the record is '
        + 'readable again. Your assistant can look at it with you.')));
  }
  add(block, cell('cell-wide cell-action', 'Folder', pathInto(make('p', 'path'), training.path),
    copyButton('Copy folder path', 'Folder path copied', training.path)));
  const sentence = sentenceFor(training);
  add(block, cell('cell-wide cell-action', 'To carry on, start your assistant in this folder and say',
    make('p', 'sentence', sentence),
    copyButton('Copy the sentence', 'Sentence copied', sentence)));
  return block;
}

function rank(name) {
  const base = name.split('@')[0];
  const at = PIPELINE.indexOf(base);
  if (at >= 0) return [at, '', 0];
  const parts = base.split(':');
  return [PIPELINE.length, parts.slice(1).join(':'), parts[0] === 'scenario' ? 0 : 1];
}

function inOrder(names) {
  return names.slice().sort((first, second) => {
    const a = rank(first);
    const b = rank(second);
    if (a[0] !== b[0]) return a[0] - b[0];
    if (a[1] !== b[1]) return a[1] < b[1] ? -1 : 1;
    return a[2] - b[2];
  });
}

function fileControl(training, name, file, state) {
  if (state === 'not-started') return pathInto(make('span', 'file file-absent'), file);
  const button = pathInto(make('button', 'file'), file);
  button.type = 'button';
  button.title = 'Show ' + file + ' as plain text';
  button.addEventListener('click', () => preview(training, name, file));
  return button;
}

function tableCell(tag, role, label, child) {
  const node = make(tag);
  node.setAttribute('role', role);
  if (label) node.dataset.label = label;
  return add(node, child);
}

function copyState(kind, state) {
  const node = make('span', 'export', kind + ': ' + state);
  node.dataset.state = state;
  return node;
}

function filesTable(training, caption, names) {
  const status = training.status;
  const table = make('table', 'files');
  table.setAttribute('role', 'table');
  if (caption) add(table, make('caption', 'label', caption));
  const head = make('tr');
  head.setAttribute('role', 'row');
  for (const title of ['Artifact', 'Status', 'File', 'Copies']) {
    const heading = make('th', 'label', title);
    heading.scope = 'col';
    heading.setAttribute('role', 'columnheader');
    head.append(heading);
  }
  const body = make('tbody');
  for (const name of inOrder(names)) {
    const row = make('tr');
    row.setAttribute('role', 'row');
    const state = status.artifacts[name];
    const file = status.files[name];
    const named = tableCell('th', 'rowheader', '', make('span', 'artifact', name.split('@')[0]));
    named.scope = 'row';
    const word = status.exports[name];
    const doc = (status.google_docs || {})[name];
    add(row, named,
      tableCell('td', 'cell', 'Status', statusWord(state)),
      tableCell('td', 'cell', 'File', fileControl(training, name, file, state)),
      add(tableCell('td', 'cell', 'Copies'),
        doc ? copyState('Google', doc) : null,
        word ? copyState('Word', word) : null));
    row.lastChild.dataset.export = word || doc ? 'kept' : 'none';
    body.append(row);
  }
  return add(table, add(make('thead'), head), body);
}

function files(training) {
  const status = training.status;
  const names = Object.keys(status.artifacts);
  const node = section('Files', names.length);
  const levels = list(status.levels);
  if (!levels.length) return add(node, filesTable(training, '', names));
  add(node, filesTable(training, 'Shared by every level',
    names.filter((name) => !name.includes('@'))));
  for (const level of levels) {
    add(node, filesTable(training, 'Level ' + level,
      names.filter((name) => name.split('@')[1] === level)));
  }
  return node;
}

function reasons(title, items, none) {
  const node = section(title, list(items).length);
  if (!list(items).length) return add(node, make('p', 'quiet', none));
  return add(node, bullets(list(items), 'reasons'));
}

function checks(check) {
  const failing = list(check.checks);
  const node = section('Checks', failing.length);
  add(node, make('p', 'quiet', words(Number(check.passed) || 0, 'check', 'checks') + ' passed.'
    + (failing.length ? '' : ' None failed, and none was unable to run.')));
  for (const outcome of failing) {
    const item = make('div', 'check');
    add(item, add(make('p', 'check-name'), make('span', 'artifact', outcome.check),
      make('span', 'check-status', outcome.status === 'unavailable' ? 'could not run' : outcome.status)));
    add(item, bullets(list(outcome.problems), 'reasons'));
    node.append(item);
  }
  return node;
}

function objectives(label, names, exercised) {
  const row = make('p', 'objectives');
  add(row, make('span', 'label', label));
  if (!names.length) return add(row, make('span', 'quiet', 'none'));
  for (const name of names) {
    add(row, add(make('span', 'objective'), mark(exercised ? 'approved' : 'not-started'),
      make('span', '', name)));
  }
  return row;
}

function practice(training) {
  const report = training.check.practice || {};
  const levels = list(training.status.levels);
  const node = section('Practice');
  add(node, make('p', 'quiet', 'Which objectives the scenarios exercise. A scenario need not cover them all.'));
  const parts = levels.length
    ? levels.filter((level) => report[level]).map((level) => ['Level ' + level, report[level]])
    : (report.basis ? [['', report]] : []);
  if (!parts.length) return add(node, make('p', 'quiet', 'There is nothing to report yet: no blueprint and scenario to compare.'));
  for (const [title, part] of parts) {
    const group = make('div', 'practice');
    if (title) add(group, make('h4', 'label', title));
    add(group, objectives('Exercised', list(part.exercised), true),
      objectives('Not exercised', list(part.not_exercised), false),
      make('p', 'quiet', 'Read from the ' + part.basis + '.'));
    node.append(group);
  }
  return node;
}

function research(status) {
  const node = section('Research');
  const summary = status.research;
  if (!summary) return add(node, make('p', 'quiet', 'The research has not been approved yet.'));
  const line = make('p', '');
  add(line, 'Approved ', when(summary.approved_at));
  if (summary.run) add(line, ', from run ', make('span', 'artifact', summary.run));
  add(line, '.');
  add(node, line);
  const found = Object.entries(summary.findings || {});
  if (found.length) {
    add(node, make('p', 'quiet', 'Findings: '
      + found.map(([state, count]) => count + ' ' + state).join(', ') + '.'));
  }
  return node;
}

function guidance(status) {
  const node = section('Guidance');
  const pin = status.guidance;
  if (!pin) return add(node, make('p', 'quiet', 'This training is not pinned to any guidance yet.'));
  const line = make('p', '');
  if (pin.commit) add(line, 'Pinned to commit ', make('span', 'artifact', String(pin.commit).slice(0, 12)));
  else add(line, 'Pinned to the guidance installed with the scripts');
  if (pin.pinned_at) add(line, ', ', when(pin.pinned_at));
  if (pin.runtime) add(line, ', by scripts version ', make('span', 'artifact', pin.runtime));
  add(line, '.');
  return add(node, line);
}

function backButton() {
  const button = make('button', 'back', 'All trainings');
  button.type = 'button';
  button.addEventListener('click', () => {
    if (view.pushed > 0) {
      window.history.back();
    } else {
      window.history.replaceState(null, '');
      showList();
    }
  });
  return button;
}

function drawSheet(training) {
  const nodes = [backButton(), titleBlock(training)];
  if (training.status && training.check) {
    nodes.push(files(training),
      reasons('Blocking', training.check.blocking, 'Nothing is blocking this training.'),
      checks(training.check),
      reasons('Limitations', training.check.limitations, 'Nothing was left out.'),
      reasons('Warnings', training.check.warnings, 'No warnings.'),
      practice(training), research(training.status), guidance(training.status));
  }
  byId('sheet-body').replaceChildren(...nodes);
}

function showList() {
  view.open = null;
  view.shown = null;
  byId('main').dataset.view = 'list';
  byId('sheet-body').hidden = true;
  byId('sheet-empty').hidden = false;
  markCurrent();
}

async function open(path) {
  view.open = path;
  byId('main').dataset.view = 'detail';
  byId('sheet-empty').hidden = true;
  byId('sheet-body').hidden = false;
  markCurrent();
  if (view.shown !== path) {
    byId('sheet-body').replaceChildren(backButton(), make('p', 'quiet', 'Reading the training.'));
  }
  try {
    const training = await ask('training' + query({ path }));
    if (view.open !== path) return;
    drawSheet(training);
    view.shown = path;
  } catch (failure) {
    if (view.open !== path) return;
    if (failure.kind === 'stopped') notify(failure.message);
    byId('sheet-body').replaceChildren(backButton(), make('p', 'sheet-problem', failure.message));
    view.shown = null;
  }
}

function choose(path) {
  window.history.pushState({ open: path }, '');
  view.pushed += 1;
  open(path);
  byId('sheet').focus({ preventScroll: WIDE.matches });
  if (!WIDE.matches) window.scrollTo(0, 0);
}

// --- a file -----------------------------------------------------------------------

async function preview(training, name, file) {
  const turn = view.preview += 1;
  const text = byId('preview-text');
  byId('preview-artifact').textContent = (training.title || 'Untitled') + ' · ' + name;
  byId('preview-title').textContent = file;
  byId('preview-note').textContent = 'Reading the file.';
  text.textContent = '';
  text.hidden = true;
  if (!byId('preview').open) byId('preview').showModal();
  let note = '';
  try {
    const shown = await ask('file' + query({ path: training.path, artifact: name }));
    if (turn !== view.preview) return;
    if (shown.binary) {
      note = file + ' is not text, so it is not shown here. It is ' + size(shown.size)
        + '. Open it from the training folder.';
    } else {
      text.textContent = shown.text;
      text.hidden = false;
      note = shown.truncated
        ? 'The start of a file of ' + size(shown.size) + ', as plain text. Open the file for the rest.'
        : size(shown.size) + ', as plain text. Nothing in it is run or rendered.';
    }
  } catch (failure) {
    if (turn !== view.preview) return;
    note = failure.message;
  }
  byId('preview-note').textContent = note;
}

// --- reading and re-reading -------------------------------------------------------

async function readAll() {
  byId('refresh').disabled = true;
  try {
    const listing = await ask('trainings');
    view.trainings = list(listing.trainings);
    view.readAt = Date.now();
    notify('');
    drawList();
    byId('read-at').textContent = 'Read at ' + new Date().toLocaleTimeString([],
      { hour: '2-digit', minute: '2-digit' });
    const paths = view.trainings.map((training) => training.path);
    if (view.open && !paths.includes(view.open)) showList();
    if (view.open) await open(view.open);
  } catch (failure) {
    // The list needs nothing but the token, so a refusal here is about the link itself.
    notify(failure.kind === 'refused' ? NOTICES.refused : failure.message);
  } finally {
    byId('refresh').disabled = false;
  }
}

// Beside the list there is room for a sheet, so one is opened without being asked for.
function openFirstIfRoom() {
  if (WIDE.matches && !view.open && view.trainings.length) open(view.trainings[0].path);
}

function linkToken() {
  const found = /(?:^#|&)token=([A-Za-z0-9_-]+)/.exec(window.location.hash);
  return found ? found[1] : '';
}

async function begin() {
  view.token = linkToken();
  // A new link pasted into a tab that is already open changes only the fragment.
  window.addEventListener('hashchange', () => {
    const next = linkToken();
    if (next && next !== view.token) {
      view.token = next;
      readAll().then(openFirstIfRoom);
    }
  });
  byId('refresh').addEventListener('click', readAll);
  byId('preview-close').addEventListener('click', () => byId('preview').close());
  byId('preview').addEventListener('click', (event) => {
    if (event.target === byId('preview')) byId('preview').close();
  });
  window.addEventListener('popstate', (event) => {
    view.pushed = Math.max(0, view.pushed - 1);
    if (event.state && event.state.open) open(event.state.open);
    else showList();
  });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && Date.now() - view.readAt > 5000) readAll();
  });
  // The link's fragment holds the token, so the skip link must not replace it.
  document.querySelector('.skip').addEventListener('click', (event) => {
    event.preventDefault();
    byId('main').focus();
  });
  WIDE.addEventListener('change', openFirstIfRoom);
  if (!view.token) {
    notify(NOTICES.refused);
    return;
  }
  const remembered = window.history.state && window.history.state.open;
  await readAll();
  const paths = view.trainings.map((training) => training.path);
  if (remembered && paths.includes(remembered)) open(remembered);
  else openFirstIfRoom();
}

begin();
