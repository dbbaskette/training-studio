// The page: home, trainings, status, settings, one training, and a gate.
// It draws what the server says and sends back only what the person decides. Every value
// from the server is placed as text, so nothing in a training's files or its record can
// ever be read as markup. Documents are drawn by markdown.js, which keeps the same rule.
'use strict';

const TOKEN_HEADER = 'X-Training-Studio-Token';
const POLL_SHOWN = 5000;
const POLL_HIDDEN = 20000;
const WORKING = 3 * 60000; // a training that changed this recently is shown as working
const DRAWING = 'http://www.w3.org/2000/svg'; // the name of the SVG language; nothing is fetched
const COUNTED = ['Nothing needs', 'One thing needs', 'Two things need', 'Three things need',
  'Four things need', 'Five things need', 'Six things need', 'Seven things need',
  'Eight things need', 'Nine things need', 'Ten things need'];
const NOTICES = {
  stopped: 'This page has lost touch with Training Studio, so it cannot read or save anything. '
    + 'Run the desk command again in your terminal and use the new link.',
  refused: 'This link does not match the page that is running. '
    + 'Run the desk command again in your terminal and use the link it prints, whole.',
};
// Every icon is drawn here, on a 24 by 24 grid, in one weight of line.
const ICONS = {
  home: ['M4 11.5 12 4.5l8 7', 'M6.5 10.5V19.5h11V10.5'],
  trainings: ['M12 4 3.5 8.5 12 13l8.5-4.5z', 'M3.5 12.5 12 17l8.5-4.5', 'M3.5 16.5 12 21l8.5-4.5'],
  status: ['M3 12.5h4l2.5-6.5 4.5 12 2.5-5.5H21'],
  settings: ['M4.5 7.5h7', 'M16.5 7.5h3', 'M14 5.5a2 2 0 1 0 0 4 2 2 0 0 0 0-4z', 'M4.5 16.5h3',
    'M12.5 16.5h7', 'M10 14.5a2 2 0 1 0 0 4 2 2 0 0 0 0-4z'],
  back: ['M14.5 5.5 8 12l6.5 6.5'],
  more: ['M6 12h.01', 'M12 12h.01', 'M18 12h.01'],
  check: ['M5.5 12.5 10 17l8.5-10'],
  eye: ['M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z',
    'M12 9.2a2.8 2.8 0 1 0 0 5.6 2.8 2.8 0 0 0 0-5.6z'],
  warn: ['M12 6v7.5', 'M12 17.5h.01'],
  minus: ['M6.5 12h11'],
  slash: ['M7 17 17 7'],
};
// The decisions that take a note. `needed` is what the page says when one is missing.
const FORMS = {
  revise: {
    title: 'Ask for changes',
    label: 'What should change?',
    hint: 'Say it in your own words. Your assistant makes the change and brings it back here.',
    needed: 'Say what should change first.',
    send: 'Send for changes',
  },
  rebuild: {
    title: 'Rebuild it',
    label: 'Anything to do differently? You can leave this empty.',
    hint: 'It is made again from what it is built from, and comes back here for your review.',
    needed: '',
    send: 'Ask for a rebuild',
  },
  skip: {
    title: 'Skip this stage',
    label: 'Why leave this stage out?',
    hint: 'The reason is kept with the training. You can bring the stage back later.',
    needed: 'Give a reason first.',
    send: 'Skip this stage',
  },
  accept: {
    title: 'Accept it as it is',
    label: 'Why is it fine as it is?',
    hint: 'What it was built from has changed. Your reason is kept with the training.',
    needed: 'Give a reason first.',
    send: 'Accept as it is',
  },
};
// The decisions that take no note. They are confirmed in the sheet before anything is sent.
const CONFIRMS = {
  approve: {
    title: (label) => 'Approve ' + label + '?',
    says: 'You are approving this version, built from what it is built from now. If either '
      + 'changes, it comes back to you.',
    send: 'Approve',
  },
  restore: {
    title: () => 'Bring this stage back?',
    says: 'It becomes part of the training again, and what it makes will come to you for review.',
    send: 'Bring it back',
  },
};
const STATES = {
  'needs-you': ['review', 'Waiting for you'],
  'in-progress': ['current', 'In progress'],
  finished: ['done', 'Finished'],
};
const STAGE_BEADS = { 'not-started': 'none', 'left-out': 'out', unavailable: 'off' };
const FILE_BEADS = {
  approved: 'done', draft: 'current', stale: 'late', 'not-started': 'none',
  skipped: 'out', unavailable: 'off',
};
const BEAD_ICONS = { done: 'check', review: 'eye', late: 'warn', out: 'minus', off: 'slash' };
const COPY_WORDS = {
  current: 'up to date', outdated: 'out of date', missing: 'not made yet',
  unavailable: 'could not be made',
};
const COMPUTER_WORDS = {
  ok: ['done', 'Ready'], missing: ['off', 'Not installed'], problem: ['late', 'Needs attention'],
};
const NAV = [['go-home', 'home', 'home'], ['go-trainings', 'trainings', 'trainings'],
  ['go-status', 'status', 'status'], ['go-settings', 'settings', 'settings']];

const view = {
  token: '', screen: 'home', path: null, artifact: null,
  listing: null, needs: 0, computer: undefined, known: null,
  gate: null, newer: null, training: null, after: null, sheet: '', opener: '', pane: 0,
  drawn: '', named: '', pushed: 0, timer: 0, turn: 0, busy: false, checking: false,
};

const byId = (id) => document.getElementById(id);
const main = () => byId('main');

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

function count(number, one, many) {
  return number + ' ' + (number === 1 ? one : many);
}

function list(value) {
  return Array.isArray(value) ? value : [];
}

function ago(then) {
  const minutes = Math.round((Date.now() - then) / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return count(minutes, 'minute', 'minutes') + ' ago';
  const hours = Math.round(minutes / 60);
  if (hours < 24) return count(hours, 'hour', 'hours') + ' ago';
  const days = Math.round(hours / 24);
  if (days < 30) return count(days, 'day', 'days') + ' ago';
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
  if (bytes < 1024) return count(bytes, 'byte', 'bytes');
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
  const held = list(levels);
  if (!held.length) return '';
  return (held.length === 1 ? 'Level ' : 'Levels ') + held.join(', ');
}

function icon(name) {
  const node = document.createElementNS(DRAWING, 'svg');
  node.setAttribute('class', 'icon');
  node.setAttribute('viewBox', '0 0 24 24');
  node.setAttribute('aria-hidden', 'true');
  node.setAttribute('focusable', 'false');
  for (const line of ICONS[name]) {
    const path = document.createElementNS(DRAWING, 'path');
    path.setAttribute('d', line);
    node.append(path);
  }
  return node;
}

function button(label, className, action, key) {
  const node = make('button', className, label);
  node.type = 'button';
  if (key) node.dataset.key = key;
  node.addEventListener('click', action);
  return node;
}

// A capsule of glass. The highlight on it follows the pointer.
function capsule(label, kind, action, key) {
  return button(label, 'button shine' + (kind ? ' button-' + kind : ''), action, key);
}

// A bead that says a state by its shape. The words beside it say the same thing.
function bead(kind) {
  const node = make('span', 'bead');
  node.dataset.state = kind;
  node.setAttribute('aria-hidden', 'true');
  if (BEAD_ICONS[kind]) node.append(icon(BEAD_ICONS[kind]));
  return node;
}

function state(kind, text) {
  return add(make('span', 'state'), bead(kind), make('span', '', text));
}

function card(title, className) {
  const node = make('section', 'card shine' + (className ? ' ' + className : ''));
  return add(node, make('h2', 'card-title', title));
}

function bullets(items, className) {
  const node = make('ul', className || 'plain');
  for (const item of items) node.append(make('li', '', item));
  return node;
}

// The row of stages, the same everywhere: beads on a thread, filling as the training goes.
function beads(stages, small) {
  const row = make('ol', 'beads' + (small ? ' beads-small' : ''));
  let told = null;
  for (const stage of list(stages)) {
    const item = make('li', 'bead-stage');
    item.dataset.state = stage.state;
    if (small) item.title = stage.name + ': ' + stage.words;
    add(item, bead(STAGE_BEADS[stage.state] || stage.state),
      make('span', small ? 'offscreen' : 'bead-name', stage.name),
      make('span', 'offscreen', ': ' + stage.words));
    row.append(item);
    if (stage.state === 'review' || (stage.state === 'current' && !told)) told = stage;
  }
  if (small || !told) return row;
  // Where there is no room for a name under every bead, the one that matters is said below.
  const caption = make('p', 'beads-caption', told.name + ': ' + told.words);
  caption.setAttribute('aria-hidden', 'true');
  return add(document.createDocumentFragment(), row, caption);
}

// A control with two answers. Its glass thumb slides to the one that is chosen.
function segmented(label, options, at, choose, key) {
  const node = make('div', 'segmented');
  node.setAttribute('role', 'group');
  node.setAttribute('aria-label', label);
  node.dataset.at = String(at);
  const thumb = make('span', 'seg-thumb');
  thumb.setAttribute('aria-hidden', 'true');
  node.append(thumb);
  options.forEach((text, index) => {
    const option = button(text, 'seg-option', () => {
      if (index !== Number(node.dataset.at)) choose(index, node);
    }, key + ' ' + index);
    option.setAttribute('aria-pressed', String(index === at));
    node.append(option);
  });
  return node;
}

function slide(node, at) {
  node.dataset.at = String(at);
  node.querySelectorAll('.seg-option').forEach((option, index) => {
    option.setAttribute('aria-pressed', String(index === at));
  });
}

// --- talking to the server ---------------------------------------------------------

class PageError extends Error {
  constructor(kind, message) {
    super(message);
    this.kind = kind;
  }
}

async function call(endpoint, options) {
  let response;
  try {
    response = await fetch('/api/' + endpoint, options);
  } catch (failure) {
    throw new PageError('stopped', NOTICES.stopped);
  }
  let body = null;
  try {
    body = await response.json();
  } catch (failure) {
    body = null;
  }
  if (response.ok && body) return body;
  const said = body && body.error ? String(body.error)
    : 'Training Studio gave no answer this page can read.';
  throw new PageError(response.status === 403 ? 'refused' : 'failed', said);
}

function ask(endpoint, params) {
  const query = params ? '?' + new URLSearchParams(params).toString() : '';
  return call(endpoint + query, { headers: { [TOKEN_HEADER]: view.token }, cache: 'no-store' });
}

function send(endpoint, body) {
  return call(endpoint, {
    method: 'POST',
    headers: { [TOKEN_HEADER]: view.token, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    cache: 'no-store',
  });
}

function notify(text) {
  byId('notice').textContent = text;
  byId('notice').hidden = !text;
}

function calm() {
  return Boolean(window.matchMedia
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
}

// A short message that slides in at the top right, is read out, and leaves by itself.
function toast(text) {
  const node = make('p', 'toast glass', text);
  byId('toasts').append(node);
  window.setTimeout(() => {
    node.classList.add('toast-leaving');
    window.setTimeout(() => node.remove(), calm() ? 0 : 260);
  }, 4200);
}

// --- copying ----------------------------------------------------------------------

function copyBySelection(text) {
  const holder = make('textarea', 'offscreen');
  holder.value = text;
  holder.readOnly = true;
  holder.setAttribute('aria-hidden', 'true');
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

function copyButton(label, done, text, key) {
  return capsule(label, '', async () => {
    toast(await copy(text) ? done : 'Not copied. Select the text instead.');
  }, key);
}

// --- the window: sidebar, toolbar, sheet ------------------------------------------------

function show(screen, where, replace) {
  const next = { screen, path: (where && where.path) || null,
    artifact: (where && where.artifact) || null };
  if (replace) {
    window.history.replaceState(next, '');
  } else {
    window.history.pushState(next, '');
    view.pushed += 1;
  }
  open(next);
}

function back() {
  if (view.pushed > 0) window.history.back();
  else show(view.screen === 'gate' ? 'training' : 'trainings', { path: view.path }, true);
}

// Change screens with the browser's own transition where it has one, and a fade where not.
function swap(update) {
  if (document.startViewTransition && !calm()) {
    const moving = document.startViewTransition(update);
    // A transition that is overtaken by the next one is dropped; the screen is drawn anyway.
    moving.ready.catch(() => {});
    moving.finished.catch(() => {});
    return moving.updateCallbackDone;
  }
  const done = update();
  const holder = main();
  holder.classList.remove('arrive');
  holder.classList.add('arrive');
  return done;
}

function open(next) {
  view.screen = next.screen || 'home';
  view.path = next.path || null;
  view.artifact = next.artifact || null;
  view.gate = null;
  view.newer = null;
  view.training = null;
  view.after = null;
  view.sheet = '';
  view.pane = 0;
  view.drawn = '';
  view.turn += 1;
  const current = view.screen === 'training' || view.screen === 'gate' ? 'trainings'
    : view.screen;
  for (const [id, screen] of NAV) {
    if (current === screen) byId(id).setAttribute('aria-current', 'page');
    else byId(id).removeAttribute('aria-current');
  }
  drawSheet();
  swap(() => draw(true));
}

// The toolbar: where you are, the way back, and the main thing to do here.
function toolbar(spec) {
  setTitle(spec.name === undefined ? spec.title : spec.name);
  byId('title').textContent = spec.title;
  const above = byId('above');
  above.replaceChildren(...list(spec.above).filter(Boolean));
  above.hidden = !above.childNodes.length;
  const lead = byId('toolbar-lead');
  lead.replaceChildren();
  if (spec.back) {
    const node = button('', 'button button-round shine', back, 'back');
    node.setAttribute('aria-label', 'Back');
    add(lead, add(node, icon('back')));
  }
  byId('actions').replaceChildren(...list(spec.actions).filter(Boolean));
}

// Put a screen in place. A screen drawn again, because something changed, keeps the
// reader's place: what had the focus has it again, and what was open stays open.
function place(spec, nodes, fresh) {
  const holder = main();
  const active = document.activeElement;
  const focused = !fresh && active && active.dataset ? active.dataset.key : '';
  const opened = fresh ? [] : Array.from(holder.querySelectorAll('details'))
    .filter((node) => node.open).map((node) => node.dataset.key);
  toolbar(spec);
  holder.replaceChildren(...nodes.filter(Boolean));
  for (const node of holder.querySelectorAll('details')) {
    if (opened.includes(node.dataset.key)) node.open = true;
  }
  if (fresh) {
    window.scrollTo(0, 0);
    byId('title').focus({ preventScroll: true });
    return;
  }
  if (focused) focusKey(focused);
}

function focusKey(key) {
  for (const node of document.querySelectorAll('[data-key]')) {
    if (node.dataset.key === key && !node.disabled) {
      node.focus({ preventScroll: true });
      return true;
    }
  }
  return false;
}

// The tab's title leads with how many things need the person, so it shows from another tab.
function setTitle(name) {
  if (name !== undefined) view.named = name;
  const waiting = view.needs ? '(' + view.needs + ') ' : '';
  document.title = waiting + (view.named ? view.named + ' · ' : '') + 'Training Studio';
  const badge = byId('needs-count');
  badge.replaceChildren(String(view.needs), make('span', 'offscreen',
    view.needs === 1 ? ' thing needs you' : ' things need you'));
  badge.hidden = !view.needs;
}

function draw(fresh) {
  if (view.screen === 'gate') return drawGate(fresh);
  if (view.screen === 'training') return drawTraining(fresh);
  const titles = { home: 'Home', trainings: 'Trainings', status: 'Status', settings: 'Settings' };
  if (!view.listing) {
    place({ title: titles[view.screen] || 'Home' },
      [make('p', 'quiet', 'Reading your trainings.')], fresh);
    return undefined;
  }
  view.drawn = JSON.stringify([view.listing, view.computer, view.checking, alerts()]);
  if (view.screen === 'trainings') return drawTrainings(fresh);
  if (view.screen === 'status') return drawStatus(fresh);
  if (view.screen === 'settings') return drawSettings(fresh);
  return drawHome(fresh);
}

// --- the sheet: it drops from the toolbar, and a decision is confirmed in it ---------------

function sheetTitle(text) {
  const node = make('h2', 'sheet-title', text);
  node.id = 'sheet-title';
  return node;
}

function openSheet(kind, opener) {
  return () => {
    for (const menu of document.querySelectorAll('.menu')) menu.open = false;
    view.sheet = kind;
    view.opener = opener;
    drawSheet();
    const field = byId('note-text');
    (field || byId('sheet')).focus();
  };
}

function closeSheet() {
  const opener = view.opener;
  view.sheet = '';
  view.after = null;
  drawSheet();
  if (view.gate) paintGate(false);
  if (!focusKey(opener)) byId('title').focus({ preventScroll: true });
}

function problemLine() {
  const node = make('p', 'problem');
  node.id = 'sheet-problem';
  node.setAttribute('role', 'alert');
  node.hidden = true;
  return node;
}

function confirmSheet(kind) {
  const spec = CONFIRMS[kind];
  const problem = problemLine();
  const confirm = capsule(spec.send, 'filled', () => decide(kind, '', problem, confirm), 'send');
  return [sheetTitle(spec.title(view.gate.label.charAt(0).toLowerCase()
    + view.gate.label.slice(1))), make('p', '', spec.says), problem,
  add(make('div', 'bar'), confirm, capsule('Cancel', 'quiet', closeSheet, 'cancel'))];
}

function noteSheet(kind) {
  const spec = FORMS[kind];
  const form = make('form', 'note');
  form.noValidate = true;
  const label = make('label', 'note-label', spec.label);
  label.htmlFor = 'note-text';
  const field = make('textarea', 'note-field');
  field.id = 'note-text';
  field.rows = 3;
  field.maxLength = 10000;
  field.dataset.key = 'note';
  field.setAttribute('aria-describedby', 'note-hint sheet-problem');
  const hint = make('p', 'quiet', spec.hint);
  hint.id = 'note-hint';
  const problem = problemLine();
  const submit = make('button', 'button shine button-filled', spec.send);
  submit.type = 'submit';
  submit.dataset.key = 'send';
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const text = field.value.trim();
    if (spec.needed && !text) {
      // Refused here, beside the control, before anything is sent.
      problem.textContent = spec.needed;
      problem.hidden = false;
      field.setAttribute('aria-invalid', 'true');
      field.focus();
      return;
    }
    decide(kind, text, problem, submit);
  });
  add(form, label, field, hint, problem,
    add(make('div', 'bar'), submit, capsule('Cancel', 'quiet', closeSheet, 'cancel')));
  return [sheetTitle(spec.title), form];
}

function afterSheet() {
  const done = view.after;
  const next = done.next;
  const nodes = [sheetTitle('Done'), make('p', '', done.said)];
  if (next) {
    nodes.push(make('p', 'quiet', 'Next: ' + next.title + '. ' + next.sentence));
    nodes.push(add(make('div', 'bar'),
      capsule(next.artifact ? 'Review the next one' : 'Open the next one', 'filled',
        () => show(next.artifact ? 'gate' : 'training',
          { path: next.path, artifact: next.artifact }), 'next'),
      capsule('Stay here', 'quiet', closeSheet, 'cancel')));
  } else {
    nodes.push(make('p', 'quiet', 'Nothing else needs you right now.'));
    nodes.push(add(make('div', 'bar'),
      capsule('Back to home', 'filled', () => show('home'), 'next'),
      capsule('Stay here', 'quiet', closeSheet, 'cancel')));
  }
  return nodes;
}

function drawSheet() {
  const holder = byId('sheet');
  const shown = view.after || (view.sheet && view.gate);
  holder.hidden = !shown;
  // While a sheet is open it holds the one filled button, so the toolbar's are put away.
  byId('actions').hidden = Boolean(shown);
  if (!shown) {
    holder.replaceChildren();
    return;
  }
  let body;
  if (view.after) body = afterSheet();
  else if (FORMS[view.sheet]) body = noteSheet(view.sheet);
  else body = confirmSheet(view.sheet);
  holder.replaceChildren(...body);
}

async function decide(decision, note, problem, pressed) {
  if (view.busy) return;
  const turn = view.turn;
  view.busy = true;
  pressed.disabled = true;
  const body = { path: view.path, artifact: view.artifact, decision };
  if (note) body.note = note;
  if (view.gate.sha256) body.seen = view.gate.sha256;
  try {
    view.after = await send('decide', body);
  } catch (failure) {
    problem.textContent = failure.message;
    problem.hidden = false;
    pressed.disabled = false;
    view.busy = false;
    return;
  }
  view.busy = false;
  if (turn !== view.turn) return;
  view.sheet = '';
  try {
    // Draw the gate as it now stands, so nothing on it still says "waiting".
    view.gate = await ask('gate', { path: view.path, artifact: view.artifact });
    view.newer = null;
    if (turn === view.turn) paintGate(false);
  } catch (failure) {
    drawSheet();
  }
  if (turn !== view.turn) return;
  byId('sheet').focus();
  refresh();
}

async function moveApproval(path, mode) {
  await send('approval', { path, mode });
  toast(mode === 'page' ? 'Decisions for this training are now made on this page.'
    : 'Decisions for this training are now made in the conversation.');
}

// Where a training is decided: a control whose thumb slides before the answer is back,
// and slides home again if the answer is no.
function approvalControl(path, title, approval, after) {
  const control = segmented('Where ' + title + ' is decided',
    ['In the conversation', 'On this page'], approval === 'page' ? 1 : 0,
    async (index, node) => {
      if (view.busy) return;
      view.busy = true;
      slide(node, index);
      try {
        await moveApproval(path, index ? 'page' : 'chat');
        view.busy = false;
        await after();
      } catch (failure) {
        slide(node, index ? 0 : 1);
        toast(failure.message);
      }
      view.busy = false;
    }, 'approval ' + path);
  return control;
}

// --- home -------------------------------------------------------------------------

function greeting() {
  const hour = new Date().getHours();
  const hello = hour < 12 ? 'Good morning.' : hour < 18 ? 'Good afternoon.' : 'Good evening.';
  const things = view.needs < COUNTED.length ? COUNTED[view.needs]
    : view.needs + ' things need';
  return hello + ' ' + things + ' you' + (view.needs ? '.' : ' right now.');
}

function openTraining(training) {
  return () => show('training', { path: training.path });
}

function reviewAction(training) {
  const waiting = training.waiting || {};
  return waiting.artifact
    ? () => show('gate', { path: training.path, artifact: waiting.artifact })
    : openTraining(training);
}

function working(training) {
  return training.state === 'in-progress'
    && Date.now() - Date.parse(training.touched_at) < WORKING;
}

function needsRow(training) {
  const waiting = training.waiting || {};
  const text = add(make('div', 'row-text'),
    make('h3', 'row-title', training.title || 'Untitled'),
    make('p', 'row-says', training.sentence));
  if (waiting.artifact && waiting.question) {
    add(text, make('p', 'row-quote', 'Your assistant asks: ' + waiting.question));
  }
  const go = capsule(waiting.artifact ? 'Review' : 'Open', '', reviewAction(training),
    'needs ' + training.path);
  go.setAttribute('aria-label', go.textContent + ': ' + (training.title || 'Untitled') + '. '
    + training.sentence);
  return add(make('li', 'row row-needs'), bead('review'), text, go);
}

function quietRow(training, kind) {
  const text = add(make('div', 'row-text'),
    make('h3', 'row-title', training.title || 'Untitled'));
  if (kind === 'in-progress') add(text, beads(training.stages, true));
  add(text, make('p', 'row-says', training.sentence));
  const go = capsule('Open', 'quiet', openTraining(training), 'open ' + training.path);
  go.setAttribute('aria-label', 'Open ' + (training.title || 'Untitled'));
  const row = make('li', working(training) ? 'row working' : 'row');
  return add(row, kind === 'finished' ? bead('done') : null, text, go);
}

function brokenRow(training) {
  const text = add(make('div', 'row-text'),
    make('h3', 'row-title', training.title || 'Untitled'),
    make('p', 'row-says', 'Its record cannot be read: ' + training.error),
    pathInto(make('p', 'path'), training.path));
  const go = capsule('Open', 'quiet', openTraining(training), 'open ' + training.path);
  go.setAttribute('aria-label', 'Open ' + (training.title || 'Untitled'));
  return add(make('li', 'row'), bead('off'), text, go);
}

function rows(title, trainings, build, className) {
  if (!trainings.length) return null;
  const node = card(title, className);
  const items = make('ul', 'rows');
  for (const training of trainings) items.append(build(training));
  return add(node, items);
}

function invitation() {
  const node = make('section', 'card shine invite');
  return add(node,
    make('h2', 'invite-title', 'Start your first training'),
    make('p', '', 'Make a folder for your topic, start your assistant in that folder, and ask '
      + 'for the training in a sentence, for example:'),
    make('p', 'sentence', 'Use training-studio to build a 101 training on rolling restarts.'),
    make('p', 'quiet', 'It appears here as soon as it exists, and this page tells you each '
      + 'time it needs you.'));
}

function alerts() {
  return typeof Notification === 'undefined' ? 'none' : Notification.permission;
}

function computerLine() {
  const node = make('p', 'foot-line');
  const result = view.computer;
  if (!result) {
    add(node, make('span', '', 'This computer has not been checked yet.'));
  } else if (result.ready) {
    add(node, state('done', 'This computer is ready.'));
  } else {
    add(node, state('late', count(list(result.wrong).length, 'thing needs', 'things need')
      + ' putting right on this computer.'));
  }
  return add(node, button(result ? 'See the details' : 'Check it on the status screen',
    'link', () => show('status'), 'computer'));
}

function pick(kind) {
  return view.listing.filter((training) => !training.error && training.state === kind);
}

function drawHome(fresh) {
  const all = view.listing;
  const first = pick('needs-you')[0];
  const lead = first ? capsule(first.waiting.artifact ? 'Review ' + first.waiting.label
    : 'Open ' + (first.title || 'Untitled'), 'filled', reviewAction(first), 'lead') : null;
  const nodes = [make('p', 'large-title', greeting())];
  if (!all.length) {
    nodes.push(invitation());
  } else {
    nodes.push(
      rows('Needs you', pick('needs-you'), needsRow, 'card-needs'),
      rows('In progress', pick('in-progress'), (training) => quietRow(training, 'in-progress')),
      rows('Finished', pick('finished'), (training) => quietRow(training, 'finished')),
      rows('Cannot be read', all.filter((training) => training.error), brokenRow));
  }
  nodes.push(add(make('footer', 'foot'), computerLine()));
  place({ title: 'Home', name: '', actions: [lead] }, nodes, fresh);
}

// --- trainings ---------------------------------------------------------------------

function trainingCard(training) {
  const node = make('li', 'card shine' + (working(training) ? ' working' : ''));
  add(node, make('h2', 'row-title', training.title || 'Untitled'));
  const go = capsule('Open', '', openTraining(training), 'open ' + training.path);
  go.setAttribute('aria-label', 'Open ' + (training.title || 'Untitled'));
  if (training.error) {
    return add(node, state('off', 'Cannot be read'), make('p', 'row-says', training.error),
      add(make('div', 'bar'), add(make('span', 'quiet'), when(training.touched_at)), go));
  }
  const [shape, words] = STATES[training.state] || STATES['in-progress'];
  if (levelsText(training.levels)) add(node, make('p', 'quiet', levelsText(training.levels)));
  return add(node, beads(training.stages, true), state(shape, words),
    make('p', 'row-says', training.sentence),
    add(make('div', 'bar'), add(make('span', 'quiet'), 'Changed ', when(training.touched_at)),
      go));
}

function drawTrainings(fresh) {
  const nodes = [];
  if (!view.listing.length) {
    nodes.push(invitation());
  } else {
    const grid = make('ul', 'grid');
    for (const training of view.listing) grid.append(trainingCard(training));
    nodes.push(make('p', 'intro lede', count(view.listing.length, 'training', 'trainings')
      + ' on this computer, the one that changed last first.'), grid);
  }
  place({ title: 'Trainings' }, nodes, fresh);
}

// --- status -----------------------------------------------------------------------

function cell(label, ...children) {
  const node = make('td');
  node.dataset.label = label;
  return add(node, ...children);
}

function statusRow(training) {
  const row = make('tr');
  const name = make('th');
  name.scope = 'row';
  add(name, make('span', 'row-title', training.title || 'Untitled'),
    levelsText(training.levels) ? make('span', 'quiet', levelsText(training.levels)) : null);
  const go = capsule('Open', 'quiet', openTraining(training), 'open ' + training.path);
  go.setAttribute('aria-label', 'Open ' + (training.title || 'Untitled'));
  if (training.error) {
    return add(row, name, cell('Stage', '—'),
      cell('Where it is', state('off', 'Cannot be read'), make('p', 'quiet', training.error)),
      cell('Last changed', when(training.touched_at)), cell('In the way', '—'), cell('', go));
  }
  const [shape, words] = STATES[training.state] || STATES['in-progress'];
  return add(row, name,
    cell('Stage', training.stage_name),
    cell('Where it is', state(shape, words), make('p', 'quiet', training.sentence)),
    cell('Last changed', when(training.touched_at)),
    cell('In the way', training.blocking ? count(training.blocking, 'thing', 'things')
      : 'Nothing'),
    cell('', go));
}

function trainingsTable() {
  const node = card('Trainings');
  if (!view.listing.length) {
    return add(node, make('p', 'quiet', 'There are no trainings on this computer yet.'));
  }
  const table = make('table', 'table');
  const head = make('tr');
  for (const title of ['Training', 'Stage', 'Where it is', 'Last changed', 'In the way', '']) {
    const top = make('th', '', title);
    top.scope = 'col';
    if (!title) add(top, make('span', 'offscreen', 'Open'));
    head.append(top);
  }
  const body = make('tbody');
  for (const training of view.listing) body.append(statusRow(training));
  return add(node, add(table, add(make('thead'), head), body));
}

function fact(found, optional) {
  const shape = found.state === 'ok' ? 'done'
    : found.state === 'problem' && !optional ? 'late' : 'none';
  const words = found.label + (found.detail ? ': ' + found.detail : '')
    + (found.state === 'ok' && !found.detail ? ': yes' : '');
  return add(make('li', 'fact'), bead(shape), make('span', '', words));
}

function computerItem(item) {
  const [shape, words] = COMPUTER_WORDS[item.state] || COMPUTER_WORDS.problem;
  const node = make('li', 'computer-item');
  const said = item.state !== 'ok' && item.optional ? words + ' (optional)' : words;
  add(node, add(make('div', 'computer-top'), make('h3', 'row-title', item.name),
    state(item.state !== 'ok' && item.optional ? 'none' : shape, said)));
  const facts = make('ul', 'facts');
  for (const found of list(item.facts)) facts.append(fact(found, item.optional));
  add(node, facts);
  if (item.fix) add(node, make('p', item.optional ? 'fix fix-optional' : 'fix', item.fix));
  return node;
}

async function checkComputer() {
  if (view.checking) return;
  view.checking = true;
  draw(false);
  try {
    view.computer = (await send('computer', {})).computer;
    toast(view.computer.ready ? 'This computer is ready.'
      : 'This computer needs something put right.');
  } catch (failure) {
    notify(failure.message);
  }
  view.checking = false;
  draw(false);
}

function computerCard() {
  const node = card('This computer');
  const result = view.computer;
  if (!result) {
    return add(node, make('p', '', 'See whether this computer has what a training needs: an '
      + 'assistant that is installed and can be reached from this network, Node, and the two '
      + 'companion skills. It asks each one for its version and nothing more.'));
  }
  const summary = make('p', 'foot-line');
  if (result.ready) add(summary, state('done', 'This computer is ready.'));
  else {
    add(summary, state('late', 'Not ready yet. To put right: '
      + list(result.wrong).join(', ') + '.'));
  }
  add(summary, add(make('span', 'quiet'), 'Checked ', when(result.checked_at), '.'));
  const items = make('ul', 'computer-items');
  for (const item of list(result.items)) items.append(computerItem(item));
  return add(node, summary, items);
}

function drawStatus(fresh) {
  const check = capsule(view.checking ? 'Checking…' : view.computer ? 'Check this computer again'
    : 'Check this computer', 'filled', checkComputer, 'check-computer');
  check.disabled = view.checking;
  place({ title: 'Status', actions: [check] }, [trainingsTable(), computerCard()], fresh);
}

// --- settings ---------------------------------------------------------------------

function alertsCard() {
  const node = card('Notifications');
  const allowed = alerts();
  if (allowed === 'none') {
    return add(node, make('p', '', 'This browser cannot show notifications. The count beside '
      + 'Home, and in the tab title, still shows what needs you.'));
  }
  if (allowed === 'granted') {
    return add(node, state('done', 'On. This browser tells you when something needs you, '
      + 'while this page is open in a tab.'));
  }
  if (allowed === 'denied') {
    return add(node, make('p', '', 'Notifications are turned off for this page in your '
      + 'browser’s own settings. The count beside Home, and in the tab title, still shows '
      + 'what needs you.'));
  }
  return add(node, make('p', '', 'Be told when a training needs you, even when this tab is '
    + 'behind another.'), add(make('div', 'bar'), capsule('Turn on notifications', 'filled',
    async () => {
      try {
        await Notification.requestPermission();
      } catch (failure) {
        // Older browsers answer through a callback; the next draw reads the result.
      }
      draw(false);
    }, 'alerts')));
}

function decidedCard() {
  const node = card('Where each training is decided');
  add(node, make('p', '', 'On this page, only you can approve a stage: your assistant is '
    + 'refused if it tries. In the conversation, you approve by telling your assistant.'));
  const held = view.listing.filter((training) => !training.error);
  if (!held.length) return add(node, make('p', 'quiet', 'There are no trainings yet.'));
  for (const training of held) {
    add(node, add(make('div', 'setting'), make('p', 'row-title', training.title || 'Untitled'),
      approvalControl(training.path, training.title || 'Untitled', training.approval,
        refresh)));
  }
  return node;
}

function drawSettings(fresh) {
  place({ title: 'Settings' }, [alertsCard(), decidedCard(), add(card('This page'),
    make('p', '', 'It runs on this computer and answers only to the link that opened it. '
      + 'Nothing you read or decide here is sent anywhere else.'))], fresh);
}

// --- a gate -----------------------------------------------------------------------

function documentBody(shown, found) {
  const node = make('article', 'paper doc');
  node.setAttribute('aria-label', found.label);
  if (shown.kind === 'missing') {
    return add(node, make('p', 'quiet', 'Nothing has been made here yet.'));
  }
  if (shown.kind === 'questions') {
    add(node, make('h2', 'doc-title', shown.topic || 'The research questions'));
    if (shown.scope) add(node, make('p', 'quiet', 'Sources: ' + shown.scope.replace('-', ' ')));
    const items = make('ol', 'questions');
    for (const item of list(shown.questions)) {
      add(items, add(make('li'), make('span', '', item.question),
        make('span', 'question-id', item.id)));
    }
    return add(node, items);
  }
  if (shown.kind === 'file') {
    return add(node, make('h2', 'doc-title', shown.file.split('/').pop()),
      make('p', '', 'This is not text, so it is not shown here. It is ' + size(shown.size)
        + '. Open it from the training folder:'),
      pathInto(make('p', 'path'), found.path + '/' + shown.file),
      copyButton('Copy where it is', 'Copied', found.path + '/' + shown.file, 'copy-file'));
  }
  if (shown.kind === 'link') {
    add(node, make('p', 'quiet', shown.file.split('/').pop() + ', ' + size(shown.size)
      + '. The deck itself is where this points:'));
  }
  add(node, window.TrainingStudioMarkdown.render(shown.text));
  if (shown.truncated) {
    add(node, make('p', 'quiet', 'This is the start of a long file of ' + size(shown.size)
      + '. Open the file for the rest.'));
  }
  return node;
}

function comparison(changed) {
  const node = make('article', 'paper diff');
  node.tabIndex = 0;
  node.setAttribute('aria-label', 'Lines added and removed since you approved it');
  for (const row of changed.rows) {
    const line = make('p', 'diff-row');
    line.dataset.kind = row.kind;
    const sign = row.kind === 'added' ? '+' : row.kind === 'removed' ? '−' : '';
    add(line, make('span', 'diff-sign', row.kind === 'gap' ? '⋯' : sign),
      row.kind === 'gap' ? null : make('span', 'diff-text', row.text));
    if (row.kind === 'added') add(line, make('span', 'offscreen', ' (added)'));
    if (row.kind === 'removed') add(line, make('span', 'offscreen', ' (removed)'));
    node.append(line);
  }
  if (changed.truncated) add(node, make('p', 'quiet', 'Only the first changes are shown.'));
  return node;
}

// What is read at a gate: the document, with what changed in it one press away.
function reading(found) {
  const node = make('div', 'reading');
  const changed = found.changes;
  if (!changed.available || changed.same || !changed.comparable) {
    return add(node, documentBody(found.document, found));
  }
  const panes = [() => documentBody(found.document, found), () => comparison(changed)];
  const holder = make('div', 'pane');
  const at = view.pane ? 1 : 0;
  add(holder, panes[at]());
  return add(node, segmented('What to read', ['The document', 'What changed'], at,
    (index, control) => {
      view.pane = index;
      slide(control, index);
      holder.replaceChildren(panes[index]());
    }, 'pane'), holder);
}

function changesNote(changed) {
  const node = make('section', 'paper aside-part');
  add(node, make('h2', 'aside-title', 'What changed'));
  if (!changed.available) {
    return add(node, make('p', 'quiet', 'You have not approved a version of this before, so '
      + 'there is nothing to compare it with.'));
  }
  if (changed.same) {
    return add(node, add(make('p', 'quiet'), 'Nothing. It is as you approved it ',
      when(changed.approved_at), '.'));
  }
  if (!changed.comparable) {
    return add(node, add(make('p', ''), 'It has changed since you approved it ',
      when(changed.approved_at), ', and it cannot be compared line by line.'));
  }
  const added = changed.rows.filter((row) => row.kind === 'added').length;
  const removed = changed.rows.filter((row) => row.kind === 'removed').length;
  return add(node, add(make('p', ''), count(added, 'line', 'lines') + ' added and '
    + count(removed, 'line', 'lines') + ' removed since you approved it ',
  when(changed.approved_at), '. Choose “What changed” above the document to see them.'));
}

function checkedNote(found) {
  const node = make('section', 'paper aside-part');
  add(node, make('h2', 'aside-title', 'Checked for you'));
  const passed = Number(found.checked.passed) || 0;
  const failing = list(found.checked.problems).length;
  if (!passed && !failing) {
    return add(node, make('p', 'quiet', 'No automatic checks apply here. It is yours to read.'));
  }
  if (passed) add(node, state('done', count(passed, 'check', 'checks') + ' passed'));
  if (failing) {
    add(node, make('p', 'quiet', count(failing, 'check', 'checks') + ' did not. See below.'));
  }
  return node;
}

function lookNote(found) {
  const node = make('section', 'paper aside-part');
  add(node, make('h2', 'aside-title', 'Worth a look'));
  const items = make('ul', 'look');
  for (const first of list(found.first)) {
    add(items, add(make('li'), state('late', 'Not ready to approve: it is built from '
      + first.label + ', which is not approved yet.'), ' ',
    button('Open that first', 'link', () => show('gate',
      { path: found.path, artifact: first.artifact }), 'first ' + first.artifact)));
  }
  for (const reason of list(found.out_of_date)) {
    add(items, add(make('li'), state('late', 'Out of date. ' + reason)));
  }
  if (found.unavailable) {
    add(items, add(make('li'), state('off', 'Could not be made: ' + found.unavailable)));
  }
  for (const failed of list(found.checked.problems)) {
    add(items, add(make('li'), state('late', 'A check ' + failed.words + ': '),
      make('code', '', failed.check), bullets(list(failed.problems), 'reasons')));
  }
  for (const request of list(found.asked)) {
    add(items, add(make('li'), add(make('p', 'foot-line'), state('current',
      request.kind === 'rebuild' ? 'You asked for a rebuild' : 'You asked for changes'),
    when(request.at)),
    request.note ? make('p', 'quote', request.note) : null,
    make('p', 'quiet', 'Your assistant does this when you go back to the conversation.')));
  }
  if (items.childNodes.length) add(node, items);
  if (found.review) {
    const notes = make('details', 'review-notes');
    notes.dataset.key = 'review';
    notes.open = true;
    add(notes, make('summary', '', 'The latest review note'),
      window.TrainingStudioMarkdown.render(found.review));
    add(node, notes);
  }
  if (!items.childNodes.length && !found.review) {
    add(node, make('p', 'quiet', 'Nothing was flagged.'));
  }
  return node;
}

function gateSignature(found) {
  return JSON.stringify([found.status, found.sha256, found.checked, found.out_of_date,
    found.review, found.asked, found.decisions, found.first, found.approval, found.stages,
    found.waiting, found.question, found.changes.same, found.changes.available]);
}

function callout(kind, ...children) {
  const node = make('div', 'paper callout');
  if (kind) node.dataset.kind = kind;
  return add(node, ...children);
}

// What the gate says before anything is decided: where it stands and what is asked.
function standing(found) {
  if (view.newer) {
    return callout('late', make('p', 'problem', 'This changed while you had it open.'),
      add(make('div', 'bar'), capsule('Show the new version', 'filled', () => {
        view.gate = view.newer;
        view.newer = null;
        paintGate(false);
      }, 'newer')));
  }
  if (found.status === 'approved' && found.approved) {
    return callout('', add(make('p', ''), 'You approved this '
      + (found.approved.by === 'page' ? 'on this page ' : 'in the conversation '),
    when(found.approved.at), '.'));
  }
  if (found.status === 'skipped') {
    return callout('', make('p', '', 'This stage is left out of the training.'));
  }
  if (found.status === 'unavailable') {
    return callout('late', make('p', '', 'This stage could not be made.'));
  }
  if (found.status === 'not-started') {
    return callout('', make('p', '', 'Nothing has been made here yet, so there is nothing '
      + 'to decide.'));
  }
  if (found.status === 'stale') {
    return callout('late', make('p', '', 'This is out of date. Have it rebuilt, or accept it '
      + 'as it is.'), found.question ? make('p', 'quiet', 'Your assistant asks: '
      + found.question) : null);
  }
  if (list(found.first).length) {
    return callout('late', make('p', '', 'This cannot be approved yet. See “Worth a look”.'));
  }
  if (found.question) {
    return callout('yours', make('p', '', 'Your assistant asks: ' + found.question));
  }
  return null;
}

// Where approving happens in the conversation, the page says so and offers one control.
function inChat(found) {
  if (found.approval === 'page') return null;
  const problem = make('p', 'problem');
  problem.setAttribute('role', 'alert');
  problem.hidden = true;
  const move = capsule('Decide on this page instead', '', async () => {
    if (view.busy) return;
    view.busy = true;
    move.disabled = true;
    try {
      await moveApproval(found.path, 'page');
      view.busy = false;
      await draw(false);
      if (!focusKey('lead')) byId('title').focus({ preventScroll: true });
    } catch (failure) {
      problem.textContent = failure.message;
      problem.hidden = false;
      move.disabled = false;
    }
    view.busy = false;
  }, 'move');
  return callout('', make('p', '', 'For this training, approving happens in your conversation '
    + 'with your assistant. You can move it here: your assistant then cannot approve '
    + 'anything, and only this page can.'), add(make('div', 'bar'), move), problem);
}

// The toolbar's side of a gate: one filled button for the main thing to do, the rest quieter.
function gateActions(found) {
  if (found.approval !== 'page' || view.newer) return [];
  const offers = list(found.decisions);
  const lead = offers.includes('approve') ? 'approve' : offers.includes('restore') ? 'restore'
    : found.status === 'stale' && offers.includes('rebuild') ? 'rebuild' : '';
  const actions = [];
  if (offers.includes('revise')) {
    actions.push(capsule('Ask for changes', '', openSheet('revise', 'revise'), 'revise'));
  }
  const rest = [];
  const item = (label, kind) => button(label, 'menu-item', openSheet(kind, 'more'),
    'menu ' + kind);
  if (offers.includes('rebuild') && lead !== 'rebuild') rest.push(item('Rebuild it', 'rebuild'));
  if (offers.includes('accept')) rest.push(item('Accept as it is', 'accept'));
  if (offers.includes('skip')) rest.push(item('Skip this stage', 'skip'));
  if (rest.length) {
    const more = make('details', 'menu');
    const opener = make('summary', 'button button-round shine');
    opener.dataset.key = 'more';
    opener.setAttribute('aria-label', 'More');
    add(more, add(opener, icon('more')), add(make('div', 'menu-list'), ...rest));
    actions.push(more);
  }
  if (lead === 'approve') {
    actions.push(capsule('Approve', 'filled', openSheet('approve', 'lead'), 'lead'));
  } else if (lead === 'restore') {
    actions.push(capsule('Bring this stage back', 'filled', openSheet('restore', 'lead'),
      'lead'));
  } else if (lead === 'rebuild') {
    actions.push(capsule('Rebuild it', 'filled', openSheet('rebuild', 'lead'), 'lead'));
  }
  return actions;
}

function paintGate(fresh) {
  const found = view.gate;
  view.drawn = gateSignature(found);
  const words = found.waiting ? ['review', found.status === 'stale'
    ? 'Out of date, and waiting for your decision' : 'Waiting for your review']
    : [FILE_BEADS[found.status], found.words.charAt(0).toUpperCase() + found.words.slice(1)];
  const intro = add(make('div', 'intro'), state(words[0], words[1]),
    beads(found.stages, false));
  const aside = add(make('aside', 'aside'), checkedNote(found), lookNote(found),
    changesNote(found.changes));
  aside.setAttribute('aria-label', 'The review');
  const above = [button(found.title, 'link', () => show('training', { path: found.path }),
    'training'), levelsText(found.levels) ? make('span', '', ' · ' + levelsText(found.levels))
    : null];
  place({ title: found.label, name: found.label + ' · ' + found.title, above, back: true,
    actions: gateActions(found) },
  [intro, inChat(found), standing(found), add(make('div', 'gate'), aside, reading(found))],
  fresh);
  drawSheet();
}

async function drawGate(fresh) {
  const turn = view.turn;
  if (fresh) {
    place({ title: 'Opening', back: true }, [make('p', 'quiet', 'Reading it.')], true);
  }
  try {
    const found = await ask('gate', { path: view.path, artifact: view.artifact });
    if (turn !== view.turn) return;
    if (!fresh && view.gate && (view.after || view.sheet)) {
      // Someone is in the middle of deciding. A newer version waits until they are done.
      if (found.sha256 !== view.gate.sha256) view.newer = found;
      return;
    }
    if (!fresh && view.gate && found.sha256 !== view.gate.sha256) {
      // Never swap the document under a reader: they say when to see the new one.
      view.newer = found;
      paintGate(false);
      return;
    }
    if (!fresh && view.gate && gateSignature(found) === view.drawn) return;
    view.gate = found;
    view.newer = null;
    paintGate(fresh);
  } catch (failure) {
    if (turn !== view.turn) return;
    if (failure.kind === 'stopped') notify(failure.message);
    if (fresh || !view.gate) {
      place({ title: 'This cannot be opened', back: true },
        [make('p', 'problem', failure.message),
          capsule('Back to home', 'filled', () => show('home'), 'home')], fresh);
    }
  }
}

// --- one training -----------------------------------------------------------------

function sentenceFor(training) {
  const path = '"' + training.path + '"';
  if (training.error) {
    return 'Use training-studio to look at the training in ' + path
      + '. Its record cannot be read: ' + training.error;
  }
  return 'Use training-studio to resume the training in ' + path
    + ' and tell me what is waiting on me.';
}

function copyState(kind, value) {
  return make('span', 'copy-state', kind + ': ' + (COPY_WORDS[value] || value));
}

function fileRow(training, file) {
  const row = make('tr');
  const name = make('th');
  name.scope = 'row';
  add(name, make('span', 'row-title', file.label));
  const shape = file.waiting ? 'review' : FILE_BEADS[file.status];
  const words = file.waiting ? 'waiting for your review'
    : file.asked ? file.words + ', changes asked for' : file.words;
  const go = capsule(file.status === 'not-started' ? 'Look' : 'Open', 'quiet',
    () => show('gate', { path: training.path, artifact: file.artifact }),
    'file ' + file.artifact);
  go.setAttribute('aria-label', 'Open ' + file.label);
  return add(row, name, cell('Where it is', state(shape, words)),
    cell('File', pathInto(make('span', 'path'), file.file)),
    cell('Copies', file.google_doc ? copyState('Google Doc', file.google_doc) : null,
      file.word_copy ? copyState('Word', file.word_copy) : null,
      !file.google_doc && !file.word_copy ? make('span', 'quiet', 'none kept') : null),
    cell('', go));
}

function filesTable(training, caption, files) {
  const table = make('table', 'table');
  if (caption) add(table, make('caption', 'table-caption', caption));
  const head = make('tr');
  for (const title of ['What', 'Where it is', 'File', 'Copies', '']) {
    const top = make('th', '', title);
    top.scope = 'col';
    if (!title) add(top, make('span', 'offscreen', 'Open'));
    head.append(top);
  }
  const body = make('tbody');
  for (const file of files) body.append(fileRow(training, file));
  return add(table, add(make('thead'), head), body);
}

function filesCard(training) {
  const node = card('Files');
  const files = list(training.view.files);
  const levels = list(training.levels);
  if (!levels.length) return add(node, filesTable(training, '', files));
  add(node, filesTable(training, 'Shared by every level', files.filter((file) => !file.level)));
  for (const level of levels) {
    add(node, filesTable(training, 'Level ' + level,
      files.filter((file) => file.level === level)));
  }
  return node;
}

function reasonsCard(title, items, none) {
  const node = card(title);
  if (!list(items).length) return add(node, make('p', 'quiet', none));
  return add(node, bullets(list(items), 'reasons'));
}

function checksCard(check) {
  const failing = list(check.checks);
  const node = card('Checks');
  add(node, make('p', 'quiet', count(Number(check.passed) || 0, 'check', 'checks') + ' passed.'
    + (failing.length ? '' : ' None failed, and none was unable to run.')));
  for (const outcome of failing) {
    add(node, add(make('div', 'check'),
      add(make('p', ''), make('code', '', outcome.check), ' ',
        make('span', 'quiet', outcome.status === 'unavailable' ? 'could not run' : 'failed')),
      bullets(list(outcome.problems), 'reasons')));
  }
  return node;
}

function objectives(label, names, exercised) {
  const row = add(make('p', 'foot-line'), make('span', 'quiet', label + ':'));
  if (!names.length) return add(row, make('span', '', 'none'));
  for (const name of names) add(row, state(exercised ? 'done' : 'none', name));
  return row;
}

function practiceCard(training) {
  const report = training.check.practice || {};
  const levels = list(training.levels);
  const node = card('Practice');
  add(node, make('p', 'quiet', 'Which objectives the scenarios exercise. '
    + 'A scenario need not cover them all.'));
  const parts = levels.length
    ? levels.filter((level) => report[level]).map((level) => ['Level ' + level, report[level]])
    : (report.basis ? [['', report]] : []);
  if (!parts.length) {
    return add(node, make('p', 'quiet', 'Nothing to report yet: there is no blueprint and '
      + 'scenario to compare.'));
  }
  for (const [title, part] of parts) {
    add(node, add(make('div', 'practice'), title ? make('h3', 'row-title', title) : null,
      objectives('Exercised', list(part.exercised), true),
      objectives('Not exercised', list(part.not_exercised), false),
      make('p', 'quiet', 'Read from the ' + part.basis + '.')));
  }
  return node;
}

function researchCard(status) {
  const node = card('Research');
  const summary = status.research;
  if (!summary) return add(node, make('p', 'quiet', 'There is no research to report yet.'));
  const line = make('p', '');
  if (summary.approved_at) add(line, 'Approved ', when(summary.approved_at));
  else add(line, 'Not approved yet');
  if (summary.run) add(line, ', from run ', make('code', '', summary.run));
  add(node, add(line, '.'));
  const found = Object.entries(summary.findings || {});
  if (found.length) {
    add(node, make('p', 'quiet', 'Findings: '
      + found.map(([kind, number]) => number + ' ' + kind).join(', ') + '.'));
  }
  return node;
}

function guidanceCard(status) {
  const node = card('Guidance');
  const pin = status.guidance;
  if (!pin) {
    return add(node, make('p', 'quiet', 'This training is not pinned to any guidance yet.'));
  }
  const line = make('p', '');
  if (pin.commit) {
    add(line, 'Pinned to commit ', make('code', '', String(pin.commit).slice(0, 12)));
  } else {
    add(line, 'Pinned to the guidance installed with the scripts');
  }
  if (pin.pinned_at) add(line, ', ', when(pin.pinned_at));
  if (pin.runtime) add(line, ', by scripts version ', make('code', '', pin.runtime));
  return add(node, add(line, '.'));
}

async function restore(stage, pressed) {
  if (view.busy) return;
  view.busy = true;
  pressed.disabled = true;
  try {
    await send('decide', { path: view.path, artifact: stage.stage, decision: 'restore' });
    toast(stage.name + ' is back.');
    view.busy = false;
    await draw(false);
    refresh();
  } catch (failure) {
    toast(failure.message);
    pressed.disabled = false;
  }
  view.busy = false;
}

function decisionsCard(training) {
  const node = card('How this training is decided');
  const onPage = training.approval === 'page';
  add(node, make('p', '', onPage
    ? 'Each stage is approved on this page. Your assistant cannot approve anything for you.'
    : 'Each stage is approved in your conversation with your assistant. You can move that '
      + 'here, so that only this page can approve.'),
  approvalControl(training.path, training.title || 'Untitled', training.approval,
    () => draw(false)));
  const out = list(training.view.left_out);
  if (out.length) {
    add(node, make('h3', 'row-title', 'Left out'));
    const items = make('ul', 'rows');
    for (const stage of out) {
      const text = add(make('div', 'row-text'), make('p', '', stage.name
        + (stage.optional ? ' (optional, and off unless you ask for it)' : '')));
      const again = onPage ? capsule(stage.optional ? 'Turn it on' : 'Bring it back', '',
        () => restore(stage, again), 'restore ' + stage.stage) : null;
      if (again) again.setAttribute('aria-label', again.textContent + ': ' + stage.name);
      add(items, add(make('li', 'row'), bead('out'), text, again));
    }
    add(node, items);
    if (!onPage) add(node, make('p', 'quiet', 'To bring one back, ask your assistant.'));
  }
  return node;
}

function folderCard(training) {
  const node = card('Carry on with your assistant');
  const sentence = sentenceFor(training);
  return add(node,
    make('p', 'quiet', 'Start your assistant in this folder:'),
    pathInto(make('p', 'path sentence'), training.path),
    add(make('div', 'bar'), copyButton('Copy the folder', 'Folder copied', training.path,
      'copy-folder')),
    make('p', 'quiet', 'Then say:'),
    make('p', 'sentence', sentence),
    add(make('div', 'bar'), copyButton('Copy the sentence', 'Sentence copied', sentence,
      'copy-sentence')));
}

function paintTraining(fresh) {
  const training = view.training;
  const above = levelsText(training.levels) ? [make('span', '', levelsText(training.levels))]
    : [];
  if (training.error) {
    place({ title: training.title || 'Untitled', above, back: true },
      [add(card('Its record cannot be read'), make('p', 'problem', training.error),
        make('p', 'quiet', 'Nothing else about this training can be shown until the record is '
          + 'readable again. Your assistant can look at it with you.')),
      folderCard(training)], fresh);
    return;
  }
  const [shape, words] = STATES[training.state] || STATES['in-progress'];
  const waiting = training.waiting;
  const lead = waiting && waiting.artifact ? capsule('Review ' + waiting.label, 'filled',
    () => show('gate', { path: training.path, artifact: waiting.artifact }), 'lead') : null;
  place({ title: training.title || 'Untitled', above, back: true, actions: [lead] },
    [add(make('div', 'intro'), state(shape, words), beads(training.stages, false),
      make('p', 'lede', training.sentence)),
    filesCard(training),
    reasonsCard('In the way', training.view.blocking, 'Nothing is in the way.'),
    checksCard(training.check),
    reasonsCard('Left out or limited', training.view.limitations, 'Nothing was left out.'),
    reasonsCard('Warnings', training.view.warnings, 'No warnings.'),
    practiceCard(training), researchCard(training.status), guidanceCard(training.status),
    decisionsCard(training), folderCard(training)], fresh);
}

async function drawTraining(fresh) {
  const turn = view.turn;
  if (fresh) {
    place({ title: 'Opening', back: true }, [make('p', 'quiet', 'Reading the training.')],
      true);
  }
  try {
    const training = await ask('training', { path: view.path });
    if (turn !== view.turn) return;
    const signature = JSON.stringify(training);
    if (!fresh && signature === view.drawn) return;
    view.training = training;
    view.drawn = signature;
    paintTraining(fresh);
  } catch (failure) {
    if (turn !== view.turn) return;
    if (failure.kind === 'stopped') notify(failure.message);
    if (fresh || !view.training) {
      place({ title: 'This cannot be opened', back: true },
        [make('p', 'problem', failure.message),
          capsule('Back to home', 'filled', () => show('home'), 'home')], fresh);
    }
  }
}

// --- staying up to date --------------------------------------------------------------

function waitingKey(training) {
  return training.path + '\n' + (training.waiting.artifact || '') + '\n'
    + (training.waiting.question || '');
}

// Tell the person, once, about each new thing that needs them.
function took(listing) {
  view.listing = list(listing.trainings);
  view.needs = Number(listing.needs) || 0;
  const waiting = view.listing.filter((training) => training.state === 'needs-you');
  const keys = waiting.map(waitingKey);
  for (const training of view.known ? waiting : []) {
    if (view.known.includes(waitingKey(training))) continue;
    const said = (training.title || 'Untitled') + ': ' + training.sentence;
    toast(said);
    if (alerts() !== 'granted') continue;
    try {
      const note = new Notification('Training Studio needs you',
        { body: said, tag: waitingKey(training) });
      note.onclick = () => window.focus();
    } catch (failure) {
      // A browser that will not show one still has the count in the tab title.
    }
  }
  view.known = keys;
}

async function refresh() {
  window.clearTimeout(view.timer);
  try {
    took(await ask('trainings'));
    if (view.computer === undefined) view.computer = (await ask('computer')).computer;
    notify('');
    setTitle();
    for (const node of document.querySelectorAll('time')) {
      const then = Date.parse(node.dateTime);
      if (!Number.isNaN(then)) node.textContent = ago(then);
    }
    if (view.screen === 'gate' || view.screen === 'training') {
      await draw(false);
    } else if (!view.busy && !view.checking && view.drawn
        !== JSON.stringify([view.listing, view.computer, view.checking, alerts()])) {
      draw(!view.drawn);
    }
  } catch (failure) {
    // Reading the list needs nothing but the key, so a refusal here is about the link.
    notify(failure.kind === 'refused' ? NOTICES.refused : failure.message);
  }
  view.timer = window.setTimeout(refresh, document.hidden ? POLL_HIDDEN : POLL_SHOWN);
}

// A highlight on glass that follows the pointer. Not when the person asked for less motion.
function followPointer() {
  if (calm()) return;
  document.addEventListener('pointermove', (event) => {
    const lit = event.target && event.target.closest ? event.target.closest('.shine') : null;
    if (!lit) return;
    const box = lit.getBoundingClientRect();
    lit.style.setProperty('--mx', (event.clientX - box.left) + 'px');
    lit.style.setProperty('--my', (event.clientY - box.top) + 'px');
  }, { passive: true });
}

function linkToken() {
  const found = /(?:^#|&)token=([A-Za-z0-9_-]+)/.exec(window.location.hash);
  return found ? found[1] : '';
}

function begin() {
  view.token = linkToken();
  // A new link pasted into a tab that is already open changes only the fragment.
  window.addEventListener('hashchange', () => {
    const next = linkToken();
    if (next && next !== view.token) {
      view.token = next;
      refresh();
    }
  });
  for (const [id, screen, drawing] of NAV) {
    const item = byId(id);
    item.prepend(icon(drawing));
    item.addEventListener('click', () => show(screen));
  }
  window.addEventListener('popstate', (event) => {
    view.pushed = Math.max(0, view.pushed - 1);
    open(event.state || { screen: 'home' });
  });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) refresh();
  });
  // Escape puts away whatever is open: a menu first, then the sheet.
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    const menus = Array.from(document.querySelectorAll('.menu')).filter((menu) => menu.open);
    if (menus.length) {
      for (const menu of menus) menu.open = false;
      focusKey('more');
    } else if (!byId('sheet').hidden && !view.busy) {
      closeSheet();
    }
  });
  document.addEventListener('click', (event) => {
    for (const menu of document.querySelectorAll('.menu')) {
      if (menu.open && !menu.contains(event.target)) menu.open = false;
    }
  });
  // The link's fragment holds the key, so the skip link must not replace it.
  document.querySelector('.skip').addEventListener('click', (event) => {
    event.preventDefault();
    main().focus();
  });
  followPointer();
  if (!view.token) {
    place({ title: 'This page needs its link' }, [], true);
    notify(NOTICES.refused);
    return;
  }
  open(window.history.state || { screen: 'home' });
  refresh();
}

begin();
