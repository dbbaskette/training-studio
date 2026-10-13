// The page: home, trainings, status, settings, one training, and a gate. With the runner
// behind it there are five more: set-up, a new training, a run, what a deck says, and a
// finished training's index.
// It draws what the server says and sends back only what the person decides. Every value
// from the server is placed as text, so nothing in a training's files or its record can
// ever be read as markup. Documents are drawn by markdown.js, which keeps the same rule.
// A slide's picture is fetched as bytes and shown from memory, never from an address.
'use strict';

const TOKEN_HEADER = 'X-Training-Studio-Token';
const POLL_SHOWN = 5000;
const POLL_HIDDEN = 20000;
const POLL_RUN = 2000; // while a run is working and its own screen is open
const WORKING = 3 * 60000; // with no run to ask, a training that changed this recently is working
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
// The screen in the sidebar that each other screen belongs to.
const PARENTS = { training: 'trainings', gate: 'trainings', run: 'trainings', new: 'trainings',
  index: 'trainings', outline: 'trainings', setup: 'settings' };

// What the runner adds. A run and each of its steps say where they are in these words.
const RUN_WORDS = {
  working: ['current', 'Working on its own'],
  waiting: ['review', 'Waiting for you'],
  paused: ['out', 'Paused'],
  stopped: ['off', 'Stopped'],
  failed: ['late', 'Stopped: something went wrong'],
  done: ['done', 'Finished here'],
};
const STEP_WORDS = {
  done: ['done', 'Done'], working: ['current', 'Working'], waiting: ['review', 'Waiting for you'],
  failed: ['late', 'Failed'], 'to-do': ['none', 'To do'],
};
const STEERED = {
  pause: 'Paused. Nothing more is started until you resume it.',
  resume: 'Carrying on.',
  stop: 'Stopped. Everything made so far is kept.',
  retry: 'Trying again.',
};
const AGENTS = ['claude', 'codex'];
const AGENT_NAMES = { claude: 'Claude Code', codex: 'Codex' };
const SHARE = ['each-decision', 'when-asked'];
// What the folder and the workspace are called become names of folders, so they are plain.
const PLAIN_NAME = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
const PLAIN_SAYS = 'Use letters, digits, dots, hyphens and underscores, with no spaces, '
  + 'starting with a letter or a digit: field-training, for example.';
const SHARE_SAYS = [
  'After each decision: your team sees the drafts, your answers and each review as soon as '
    + 'you decide a stage, finished or not.',
  'Only when I ask: everything stays on this computer, and your team sees nothing new, '
    + 'until you press “Share now”.',
];
const PURPOSES = ['Field enablement', 'Technical upskilling', 'General knowledge'];
const LEVELS = ['101', '201', '301', '401'];
const DECKS = [['pptx', 'PowerPoint'], ['google', 'Google Slides'], [null, 'No deck']];
const COPIES = [['google', 'Google Docs'], ['word', 'Word']];
const STEPS = ['The topic and who it is for', 'Its shape', 'The sources, the agent and the limits'];
// Where the research looks. What each answer means is said under the choice.
const SOURCES = [['public-web', 'The public web'], ['supplied-only', 'Your documents only'],
  ['both', 'Both']];
const SOURCE_SAYS = [
  'The public web: it searches for pages anyone can read, and keeps every page it quotes '
    + 'with the training.',
  'Your documents only: it reads the documents you give it and nothing else, and never '
    + 'searches the web or opens a page. You add them right after starting, and they stay on '
    + 'this computer.',
  'Both: it reads your documents and researches the public web as well. You add the '
    + 'documents right after starting, and they stay on this computer.',
];
// A training where the run has made everything it can, and the deck is all that is left.
const DECK_LEFT = 'Everything but the slide deck is made: make the deck with your assistant, '
  + 'or leave it out.';
const SETTLED = ['done', 'left-out', 'unavailable'];
// Who wrote a practice scenario. A person's own file is never rewritten for them.
const WHOSE = {
  you: 'This file is yours: you wrote it, and Training Studio does not rewrite it. If you ask '
    + 'for changes, your own wording is laid out under the headings, and you are asked for '
    + 'anything that is missing.',
  runner: 'This file is Training Studio’s draft, written from the practice plan in the '
    + 'blueprint.',
};
// A copy of a guide, a brief or a Yoodli scenario, and where it stands.
const COPY_KINDS = { google: 'Google Doc', word: 'Word copy' };
const COPY_STATES = {
  made: ['done', 'Made'], 'out-of-date': ['late', 'Out of date'], 'not-made': ['off', 'Not made'],
};
const WEB_LINK = /^https?:\/\/\S+$/i;
const KEPT_HERE = 'Your documents stay on this computer and are never shared with your team. '
  + 'Passages quoted from them appear in the research report, which is shared.';
// How the pictures of a deck's slides are made while it is drawn. What each way means is
// said under the choice.
const PREVIEWS = ['local', 'drive'];
const PREVIEW_NAMES = ['LibreOffice', 'Google Drive'];
const PREVIEW_SAYS = [
  'LibreOffice: the pictures are made on this computer, and nothing leaves it.',
  'Google Drive: each deck keeps one presentation named “Preview: …” in your Drive, written '
    + 'again at each render. Training Studio never deletes it. Settings lists the ones it '
    + 'made, each with its address, so that you can.',
];
const PREVIEW_ABSENT = [
  'LibreOffice was not found on this computer, so Google Drive is the one way there is.',
  'Google access on this computer does not reach Drive, so LibreOffice is the one way there '
    + 'is.',
];
const PREVIEW_WORDS = { local: 'made with LibreOffice, on this computer',
  drive: 'made through Google Drive' };
// A section of a deck while it is drawn, and a finding of the review by how much it matters.
const SECTION_WORDS = {
  'to-do': ['none', 'Not started'], working: ['current', 'Being drawn'],
  done: ['done', 'Handed in'], failed: ['late', 'Could not be drawn'],
};
const SEVERITIES = { critical: ['late', 'Critical'], major: ['late', 'Major'],
  minor: ['none', 'Minor'] };
const SERIOUS = ['critical', 'major'];
// What a brand's own check answers when it has nothing to raise.
const AUDIT_QUIET = ['ok', 'clear', 'clean', 'pass', 'passed', 'fine', 'success'];
// What the page says once what a deck says is decided. A gate's decision is answered by the
// server in these words; this one is answered with the run, which says what it does next.
const OUTLINE_SAID = {
  approve: 'Approved.',
  revise: 'Your changes are noted. Once they are made, the new version comes back here for '
    + 'your review.',
};
const OUTLINE_APPROVES = 'You are approving what each slide says. The slides are drawn from '
  + 'these words and come to you again as a deck. If the blueprint or the guide changes, '
  + 'this comes back to you.';
const CLOSE = 'You can close this page; it says when it needs you again.';
const HALTED = 'This training is not running, so nothing more happens until you resume it or '
  + 'try again.';

const view = {
  token: '', screen: 'home', path: null, artifact: null,
  listing: null, needs: 0, computer: undefined, known: null,
  gate: null, newer: null, training: null, after: null, sheet: '', opener: '', pane: 0,
  drawn: '', named: '', pushed: 0, timer: 0, turn: 0, busy: false, checking: false,
  // What the runner adds. `runner` is undefined until it has been asked for, and false on the
  // plain desk, where nothing below is ever used.
  runner: undefined, setup: null, form: null, draft: null, run: null, promised: null,
  asks: {}, answers: {}, agents: null, looking: false, unlooked: '', sharing: false,
  steered: '', barred: '',
  // What a sheet opened from a run decides, what a gate is read beside, and what was said
  // no to on a run: a document, the end of adding them, another try at the copies.
  deciding: null, beside: null, unadded: '', undone: '', copying: false, uncopied: '',
  // The slide a deck's gate is showing and the way to turn to another, and the pictures of
  // slides this screen holds: each by what it is of, those still to fetch, and what says
  // when one comes into view.
  slide: 0, viewer: null, pictures: new Map(), wanted: [], fetching: false, watcher: null,
};
// Each part of a screen that is drawn in parts, and what it was drawn from.
const PARTS = new WeakMap();
// Each place a picture goes, and which picture that is.
const PLACES = new WeakMap();

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

// Several things named in a row: "one, two and three".
function series(items) {
  return items.length < 2 ? items.join('')
    : items.slice(0, -1).join(', ') + ' and ' + items[items.length - 1];
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

// A limit, in the round numbers a limit is set in: 8,000,000 bytes is 8 MB.
function megabytes(bytes) {
  return String(Math.round(bytes / 100000) / 10) + ' MB';
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

// A control with two answers, or three. Its glass thumb slides to the one that is chosen.
function segmented(label, options, at, choose, key) {
  const node = make('div', 'segmented');
  node.setAttribute('role', 'group');
  node.setAttribute('aria-label', label);
  node.dataset.at = String(at);
  node.dataset.count = String(options.length);
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

// A line beside a control that says why it was refused. It is read out when it appears.
function alertLine(id) {
  const node = make('p', 'problem');
  node.id = id;
  node.setAttribute('role', 'alert');
  node.hidden = true;
  return node;
}

function say(problem, text) {
  problem.textContent = text;
  problem.hidden = !text;
}

// A labelled box to type in. What is typed is kept in `held[name]` as it is typed, so a
// screen that is drawn again still has it. With `picked` it is the browser's own file picker
// instead: nothing of it is kept, and what is chosen is handed to `picked`. With `options`,
// each a value and its name, it is the browser's own list to choose one from.
function field(id, label, held, name, about) {
  const spec = about || {};
  const title = make('label', 'field-label', label);
  title.htmlFor = id;
  const input = make(spec.long ? 'textarea' : spec.options ? 'select' : 'input',
    'input' + (spec.short ? ' input-short' : ''));
  input.id = id;
  if (spec.long) input.rows = 3;
  else if (!spec.options) input.type = spec.picked ? 'file' : 'text';
  if (spec.picked) {
    input.multiple = true;
    input.accept = spec.accept || '';
    input.addEventListener('change', () => spec.picked(input));
  } else {
    for (const [value, text] of spec.options || []) {
      const option = make('option', '', text);
      option.value = value;
      input.append(option);
    }
    input.value = held[name] || '';
    input.maxLength = spec.long ? 4000 : 400;
    input.autocomplete = 'off';
    input.spellcheck = Boolean(spec.long);
    input.addEventListener('input', () => {
      held[name] = input.value;
      // A box that is being put right no longer says it is wrong.
      if (input.getAttribute('aria-invalid')) refuse(id, '');
      if (spec.typed) spec.typed();
    });
  }
  if (spec.mode) input.inputMode = spec.mode;
  input.dataset.key = id;
  const hint = spec.hint ? make('p', 'quiet field-hint', spec.hint) : null;
  if (hint) hint.id = id + '-hint';
  input.setAttribute('aria-describedby', (hint ? id + '-hint ' : '') + id + '-problem');
  if (spec.changed) input.addEventListener('change', spec.changed);
  const problem = alertLine(id + '-problem');
  // Drawn again after it was refused, it still says why.
  if (spec.refused) {
    say(problem, spec.refused);
    input.setAttribute('aria-invalid', 'true');
  }
  return add(make('div', 'field'), title, input, hint, problem);
}

// Refuse what is in a field, beside it, before anything is sent. Returns the field.
function refuse(id, text) {
  const input = byId(id);
  say(byId(id + '-problem'), text);
  if (text) input.setAttribute('aria-invalid', 'true');
  else input.removeAttribute('aria-invalid');
  return input;
}

// One choice among two or three, with its name above it and what it means below.
function choice(label, options, at, choose, key, hint) {
  const control = segmented(label, options, at, (index, node) => {
    slide(node, index);
    choose(index);
  }, key);
  return add(make('div', 'field'), make('p', 'field-label', label), control,
    hint ? make('p', 'quiet field-hint', hint) : null);
}

// A choice with what each of its answers means spelled out under it. The one that is chosen
// is marked there too.
function explained(label, options, says, at, choose, key) {
  const meanings = make('ul', 'reasons meanings');
  const mark = (chosen) => Array.from(meanings.children).forEach((item, index) => {
    if (index === chosen) item.dataset.chosen = 'true';
    else delete item.dataset.chosen;
  });
  for (const text of says) meanings.append(make('li', '', text));
  mark(at);
  return [choice(label, options, at, (index) => {
    choose(index);
    mark(index);
  }, key), meanings];
}

// A capsule that is on or off. A tick says it is on, so it does not rest on colour.
function chip(label, on, flip, key) {
  const node = button('', 'chip', () => {
    const now = node.getAttribute('aria-pressed') !== 'true';
    node.setAttribute('aria-pressed', String(now));
    flip(now);
  }, key);
  node.setAttribute('aria-pressed', String(Boolean(on)));
  return add(node, icon('check'), make('span', '', label));
}

function money(dollars) {
  return '$' + Number(dollars).toFixed(2);
}

function lasted(seconds) {
  const whole = Math.round(Number(seconds));
  if (whole < 60) return count(whole, 'second', 'seconds');
  const minutes = Math.round(whole / 60);
  if (minutes < 60) return count(minutes, 'minute', 'minutes');
  return count(Math.floor(minutes / 60), 'hour', 'hours') + ' '
    + count(minutes % 60, 'minute', 'minutes');
}

function lower(text) {
  return String(text).charAt(0).toLowerCase() + String(text).slice(1);
}

function capital(text) {
  return String(text).charAt(0).toUpperCase() + String(text).slice(1);
}

// A word the runner uses for a kind or a state, as a person would write it.
function spoken(word) {
  return capital(String(word).replace(/[-_]+/g, ' '));
}

function given(value) {
  return value !== null && value !== undefined;
}

// --- talking to the server ---------------------------------------------------------

class PageError extends Error {
  constructor(kind, message, status) {
    super(message);
    this.kind = kind;
    this.status = status || 0;
  }
}

// One request to the server. With no answer at all, the page has lost touch with it.
async function reach(endpoint, options) {
  try {
    return await fetch('/api/' + endpoint, options);
  } catch (failure) {
    throw new PageError('stopped', NOTICES.stopped);
  }
}

// What an answer says, where it can be read, and the refusal an answer that says no makes.
async function saidBy(response) {
  try {
    return await response.json();
  } catch (failure) {
    return null;
  }
}

function refusal(response, body) {
  const said = body && body.error ? String(body.error)
    : 'Training Studio gave no answer this page can read.';
  return new PageError(response.status === 403 ? 'refused' : 'failed', said, response.status);
}

async function call(endpoint, options) {
  const response = await reach(endpoint, options);
  const body = await saidBy(response);
  if (response.ok && body) return body;
  throw refusal(response, body);
}

function ask(endpoint, params) {
  const query = params ? '?' + new URLSearchParams(params).toString() : '';
  return call(endpoint + query, { headers: { [TOKEN_HEADER]: view.token }, cache: 'no-store' });
}

// One slide's picture, as its bytes. It is asked for like everything else that is read, with
// the key, which an address written into the page could not send.
async function picture(params) {
  const response = await reach('slide?' + new URLSearchParams(params).toString(),
    { headers: { [TOKEN_HEADER]: view.token }, cache: 'no-store' });
  if (!response.ok) throw refusal(response, await saidBy(response));
  let held = null;
  try {
    held = await response.blob();
  } catch (failure) {
    held = null;
  }
  if (!held) throw new PageError('failed', 'It did not arrive whole.');
  if (!/^image\/png\b/.test(held.type)) {
    throw new PageError('failed', 'What came back is not a picture.');
  }
  return held;
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

// --- pictures of slides ------------------------------------------------------------------
// Each picture is fetched as bytes, kept in memory, and shown from there under an address
// that only this page holds. They are fetched one at a time: the one being looked at first,
// and each of the others when its place comes into view. Leaving the screen lets go of all.

// What says when a picture's place comes into view.
function watcher() {
  if (!view.watcher) {
    view.watcher = new IntersectionObserver((seen) => {
      for (const found of seen) {
        if (!found.isIntersecting) continue;
        view.watcher.unobserve(found.target);
        wantPicture(PLACES.get(found.target), false);
      }
    }, { rootMargin: '200px' });
  }
  return view.watcher;
}

// Put a picture in line to be fetched. `first` puts it at the head of the line.
function wantPicture(place, first) {
  let held = view.pictures.get(place.key);
  if (!held) {
    held = { state: 'wanted', where: place.where, url: '', says: '' };
    view.pictures.set(place.key, held);
  }
  if (held.state !== 'wanted') return;
  const at = view.wanted.indexOf(place.key);
  if (at >= 0 && !first) return;
  if (at >= 0) view.wanted.splice(at, 1);
  if (first) view.wanted.unshift(place.key);
  else view.wanted.push(place.key);
  fetchPictures();
}

async function fetchPictures() {
  if (view.fetching) return;
  view.fetching = true;
  try {
    while (view.wanted.length) {
      const key = view.wanted.shift();
      const held = view.pictures.get(key);
      if (!held) continue;
      held.state = 'fetching';
      let found = null;
      try {
        found = await picture({ path: view.path, ...held.where });
      } catch (failure) {
        held.says = failure.message;
      }
      // The screen was left meanwhile, or this picture is no longer on it: it is not kept.
      if (view.pictures.get(key) !== held) continue;
      held.state = found ? 'here' : 'failed';
      if (found) held.url = URL.createObjectURL(found);
      for (const node of document.querySelectorAll('.frame')) {
        if (PLACES.get(node).key === key) fillFrame(node);
      }
    }
  } finally {
    view.fetching = false;
  }
}

// What a picture's place shows: the picture once it is here, and words until then. A picture
// that cannot be had says so in its place, and never leaves a gap.
function fillFrame(node) {
  const place = PLACES.get(node);
  const held = view.pictures.get(place.key);
  const says = (className, text) => add(make('span', 'frame-says ' + className),
    make('span', 'offscreen', place.alt + '. '), text);
  if (held && held.state === 'here') {
    const image = make('img', 'picture');
    image.alt = place.alt;
    image.src = held.url;
    image.addEventListener('error', () => {
      node.replaceChildren(says('problem', 'What was fetched cannot be shown as a picture.'));
    });
    node.replaceChildren(image);
  } else if (held && held.state === 'failed') {
    const again = place.again ? button('Try this picture again', 'link', () => {
      view.pictures.delete(place.key);
      wantPicture(place, true);
      fillFrame(node);
      node.focus({ preventScroll: true });
    }, 'picture-again') : null;
    node.replaceChildren();
    add(node, says('problem', 'Its picture could not be fetched. ' + held.says
      + (again ? ' The deck itself is as it was.' : '')), again);
  } else {
    node.replaceChildren(says('quiet', 'Its picture is on its way.'));
  }
}

// The place a picture goes. `where` is what it is of, `alt` says so in words, and `mark`
// changes when a newer picture of the same thing is made. `about.first` is for the one being
// looked at, and `about.again` offers another try where one could not be fetched.
function pictureAt(where, alt, mark, about) {
  const spec = about || {};
  const node = make('span', 'frame');
  const place = { key: JSON.stringify([where, mark || '']), where, alt,
    again: Boolean(spec.again) };
  PLACES.set(node, place);
  if (place.again) node.tabIndex = -1;
  fillFrame(node);
  // A browser that cannot say when a place comes into view is asked for each in turn.
  if (spec.first || typeof IntersectionObserver === 'undefined') wantPicture(place, spec.first);
  else if (!view.pictures.has(place.key)) watcher().observe(node);
  return node;
}

// A picture that nothing on the screen shows any more, such as a section's earlier preview,
// is let go.
function tidyPictures() {
  const shown = new Set(Array.from(document.querySelectorAll('.frame'))
    .map((node) => PLACES.get(node).key));
  for (const [key, held] of Array.from(view.pictures)) {
    if (shown.has(key)) continue;
    if (held.url) URL.revokeObjectURL(held.url);
    view.pictures.delete(key);
  }
  view.wanted = view.wanted.filter((key) => shown.has(key));
}

// Leaving a screen lets go of every picture it held, and stops waiting for the rest.
function letGo() {
  for (const held of view.pictures.values()) {
    if (held.url) URL.revokeObjectURL(held.url);
  }
  view.pictures = new Map();
  view.wanted = [];
  if (view.watcher) view.watcher.disconnect();
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
  if (view.pushed > 0) {
    window.history.back();
    return;
  }
  const up = { gate: homeOf(view.path), index: homeOf(view.path), outline: 'run', new: 'home',
    setup: 'settings' };
  show(up[view.screen] || 'trainings', { path: view.path }, true);
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
  view.screen = unset() ? 'setup' : next.screen || 'home';
  view.path = next.path || null;
  view.artifact = next.artifact || null;
  view.gate = null;
  view.newer = null;
  view.training = null;
  view.after = null;
  view.sheet = '';
  view.pane = 0;
  view.drawn = '';
  view.run = null;
  view.form = null;
  view.steered = '';
  view.barred = '';
  view.deciding = null;
  view.beside = null;
  view.unadded = '';
  view.undone = '';
  view.copying = false;
  view.uncopied = '';
  view.slide = 0;
  view.viewer = null;
  letGo();
  view.turn += 1;
  frame();
  const current = PARENTS[view.screen] || view.screen;
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

// Everything a list screen is drawn from. When none of it has changed, nothing is redrawn.
function signature() {
  return JSON.stringify([view.listing, view.computer, view.checking, alerts(), view.setup,
    view.asks, view.sharing]);
}

function draw(fresh) {
  if (view.screen === 'gate') return drawGate(fresh);
  if (view.screen === 'training') return drawTraining(fresh);
  if (view.screen === 'run') return drawRun(fresh);
  if (view.screen === 'outline') return drawOutline(fresh);
  if (view.screen === 'index') return drawIndex(fresh);
  if (view.screen === 'setup' && view.setup) return drawSetup(fresh);
  const titles = { home: 'Home', trainings: 'Trainings', status: 'Status', settings: 'Settings',
    setup: 'Set-up', new: 'New training' };
  if (!view.listing) {
    place({ title: titles[view.screen] || 'Home' },
      [make('p', 'quiet', 'Reading your trainings.')], fresh);
    return undefined;
  }
  // Only the runner has these two screens. On the plain desk a stray visit lands on home.
  if (view.screen === 'setup' || (view.screen === 'new' && !view.runner)) {
    show('home', null, true);
    return undefined;
  }
  if (view.screen === 'new') return drawNew(fresh);
  view.drawn = signature();
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
  view.deciding = null;
  drawSheet();
  if (view.gate) paintGate(false);
  else if (view.screen === 'run' && view.run) paintRun(false);
  else if (outlined()) paintOutline(false);
  if (!focusKey(opener)) byId('title').focus({ preventScroll: true });
}

function problemLine() {
  const node = make('p', 'problem');
  node.id = 'sheet-problem';
  node.setAttribute('role', 'alert');
  node.hidden = true;
  return node;
}

// What a sheet's decision is sent with: a gate's own, or the one for what a deck says.
function decider() {
  return outlined() ? decideOutline : decide;
}

function confirmSheet(kind) {
  const spec = CONFIRMS[kind];
  const problem = problemLine();
  const confirm = capsule(spec.send, 'filled', () => decider()(kind, '', problem, confirm),
    'send');
  const about = outlined() ? [outlineLabel(view.run.outline), OUTLINE_APPROVES]
    : [lower(view.gate.label), spec.says];
  // A deck is approved as it is. What the review still finds in it is said before it is.
  const left = kind === 'approve' && view.gate ? serious(view.gate).length : 0;
  return [sheetTitle(spec.title(about[0])), make('p', '', about[1]),
    left ? state('late', 'The review still lists ' + count(left, 'serious finding',
      'serious findings') + '. Approving takes the deck as it is.') : null, problem,
    add(make('div', 'bar'), confirm, capsule('Cancel', 'quiet', closeSheet, 'cancel'))]
    .filter(Boolean);
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
  const hint = make('p', 'quiet', runOf(view.path) ? spec.hint.replace('Your assistant makes',
    'Training Studio makes') : spec.hint);
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
    decider()(kind, text, problem, submit);
  });
  add(form, label, field, hint, problem,
    add(make('div', 'bar'), submit, capsule('Cancel', 'quiet', closeSheet, 'cancel')));
  return [sheetTitle(spec.title), form];
}

function afterSheet() {
  const done = view.after;
  const next = done.next;
  const nodes = [sheetTitle('Done'), make('p', '', done.said)];
  // A training that runs on its own carries on from here, and its run is the place to watch.
  // Decided from the run itself, that is where the person already is.
  const watch = runOf(view.path) && view.screen !== 'run' ? capsule('Watch it carry on', '',
    () => show('run', { path: view.path }), 'watch') : null;
  if (next) {
    // What is next is a gate to review, what a deck says to review, or a training to open.
    const to = next.artifact ? 'gate' : next.outline ? 'outline' : homeOf(next.path);
    nodes.push(make('p', 'quiet', 'Next: ' + next.title + '. ' + next.sentence));
    nodes.push(add(make('div', 'bar'),
      capsule(next.artifact || next.outline ? 'Review the next one' : 'Open the next one',
        'filled', () => show(to, { path: next.path, artifact: next.artifact }), 'next'),
      watch, capsule('Stay here', 'quiet', closeSheet, 'cancel')));
  } else {
    nodes.push(make('p', 'quiet', 'Nothing else needs you right now.'));
    nodes.push(add(make('div', 'bar'),
      capsule('Back to home', 'filled', () => show('home'), 'next'),
      watch, capsule('Stay here', 'quiet', closeSheet, 'cancel')));
  }
  return nodes;
}

function drawSheet() {
  const holder = byId('sheet');
  const shown = view.after || (view.sheet && (view.gate || view.deciding || outlined()));
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
  // At a gate, what is decided is what is being read. A sheet opened from a run names it.
  const body = { path: view.path, artifact: view.deciding || view.artifact, decision };
  if (note) body.note = note;
  if (view.gate && view.gate.sha256) body.seen = view.gate.sha256;
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
  view.deciding = null;
  try {
    if (view.gate) {
      // Draw the gate as it now stands, so nothing on it still says "waiting".
      view.gate = await ask('gate', { path: view.path, artifact: view.artifact });
      view.newer = null;
      if (turn === view.turn) paintGate(false);
    } else {
      // Decided from a run, which is read again below and then shows what follows.
      if (view.run) paintRun(false);
      drawSheet();
    }
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

// A training that runs on its own opens on its run; any other opens on its own view.
function openTraining(training) {
  return () => show(training.run ? 'run' : 'training', { path: training.path });
}

function reviewAction(training) {
  const waiting = training.waiting || {};
  return waiting.artifact
    ? () => show('gate', { path: training.path, artifact: waiting.artifact })
    : openTraining(training);
}

// A run says whether it is working. Only where there is no run is it guessed, from how
// lately the training changed.
function working(training) {
  if (training.run) return training.run.state === 'working';
  return training.state === 'in-progress'
    && Date.now() - Date.parse(training.touched_at) < WORKING;
}

// One sentence for a training in a list. A run says what it is doing now; a gate says what
// is waiting. Where the deck is all that is left, that is the one thing said.
function saysOf(training) {
  if (deckLeft(training)) return DECK_LEFT;
  const atGate = training.state === 'needs-you' && (training.waiting || {}).artifact;
  return (training.run && !atGate && training.run.sentence) || training.sentence;
}

function needsRow(training, index) {
  const waiting = training.waiting || {};
  const asked = view.asks[training.path] || {};
  const title = training.title || 'Untitled';
  const text = add(make('div', 'row-text'), make('h3', 'row-title', title));
  const says = asked.problem ? asked.problem.what : saysOf(training);
  if (asked.question) {
    add(text, questionBox(training.path, title, asked.question, '', 'answer-' + index));
  } else {
    add(text, make('p', 'row-says', says));
    if (waiting.artifact && waiting.question && !asked.problem) {
      add(text, make('p', 'row-quote', asker(training.path) + waiting.question));
    }
  }
  const review = waiting.artifact && !asked.question && !asked.problem;
  // What a deck says is reviewed on a screen of its own, reached from here like any gate.
  const outline = !waiting.artifact && readsOutline(asked);
  const go = capsule(review || outline ? 'Review' : 'Open', asked.question ? 'quiet' : '',
    outline ? () => show('outline', { path: training.path })
      : review ? reviewAction(training) : openTraining(training), 'needs ' + training.path);
  go.setAttribute('aria-label', go.textContent + ': ' + title + '. '
    + (asked.question ? asked.question.text : says));
  return add(make('li', 'row row-needs'), bead(asked.problem ? 'late' : 'review'), text, go);
}

function quietRow(training, kind) {
  const text = add(make('div', 'row-text'),
    make('h3', 'row-title', training.title || 'Untitled'));
  if (kind === 'in-progress') add(text, beads(training.stages, true));
  // A run that is not working says so: paused, stopped, or finished as far as it goes here.
  if (training.run && training.run.state !== 'working' && kind === 'in-progress'
      && !deckLeft(training)) {
    add(text, state(...runWords(training.run)));
  }
  add(text, make('p', 'row-says', saysOf(training)));
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
  trainings.forEach((training, index) => items.append(build(training, index)));
  return add(node, items);
}

function invitation() {
  const node = make('section', 'card shine invite');
  if (view.runner) {
    return add(node,
      make('h2', 'invite-title', 'Start your first training'),
      make('p', '', 'Say what it is about and who it is for. Training Studio does the '
        + 'research and writes the blueprint, the learner guide, the brief and the practice '
        + 'scenarios on its own, and stops each time it needs your decision.'),
      add(make('div', 'bar'), newButton('filled')),
      make('p', 'quiet', 'It takes three short steps, and this page tells you each time it '
        + 'needs you.'));
  }
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
  const asked = first ? view.asks[first.path] : null;
  const gate = first && (first.waiting || {}).artifact && !asked;
  const outline = first && !(first.waiting || {}).artifact && readsOutline(asked);
  const lead = !first ? null : outline ? capsule('Review ' + outlineLabel(asked.outline),
    'filled', () => show('outline', { path: first.path }), 'lead')
    : capsule(gate ? 'Review ' + first.waiting.label : 'Open ' + (first.title || 'Untitled'),
      'filled', gate ? reviewAction(first) : openTraining(first), 'lead');
  // With the runner, one button starts a new training. It is the filled one when nothing
  // needs the person first.
  const start = view.runner && all.length ? newButton(lead ? '' : 'filled') : null;
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
  nodes.push(add(make('footer', 'foot'), computerLine(), sharingLine()));
  place({ title: 'Home', name: '', actions: [start, lead] }, nodes, fresh);
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
  const [shape, words] = standingOf(training);
  if (levelsText(training.levels)) add(node, make('p', 'quiet', levelsText(training.levels)));
  return add(node, beads(training.stages, true), state(shape, words),
    make('p', 'row-says', saysOf(training)),
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
  place({ title: 'Trainings', actions: [view.runner && view.listing.length
    ? newButton('filled') : null] }, nodes, fresh);
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
  const [shape, words] = standingOf(training);
  return add(row, name,
    cell('Stage', training.stage_name),
    cell('Where it is', state(shape, words), make('p', 'quiet', saysOf(training))),
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
      + 'companion skills. It asks each one for its version and nothing more.'),
    // With the runner, a deck is made here too, and what that needs is checked with the rest.
    view.runner ? make('p', 'quiet', 'A slide deck needs more: the slides skill, a brand '
      + 'skill, a way to make previews, and the programs that turn a render into pictures. '
      + 'Each is listed with the rest, with what to do about it.') : null);
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
  // A training that runs on its own is always decided here, so there is nothing to choose.
  const held = view.listing.filter((training) => !training.error && !training.run);
  if (!held.length) {
    return add(node, make('p', 'quiet', view.listing.some((training) => training.run)
      ? 'Every training here runs from this page, and is decided on it.'
      : 'There are no trainings yet.'));
  }
  for (const training of held) {
    add(node, add(make('div', 'setting'), make('p', 'row-title', training.title || 'Untitled'),
      approvalControl(training.path, training.title || 'Untitled', training.approval,
        refresh)));
  }
  return node;
}

function drawSettings(fresh) {
  place({ title: 'Settings' }, [workspaceCard(), leftCard(), alertsCard(), decidedCard(),
    add(card('This page'),
      make('p', '', 'It runs on this computer and answers only to the link that opened it. '
        + (view.runner ? 'The page sends what you read and decide nowhere else. The agent that '
          + 'does the drafting is sent what it needs for each step, by its own service.'
          : 'Nothing you read or decide here is sent anywhere else.')))], fresh);
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
      make('p', '', (slidesOf(found).length ? 'The pictures above are of this file. It is '
        : 'This is not text, so it is not shown here. It is ') + size(shown.size)
        + '. Open it from the training folder:'),
      pathInto(make('p', 'path'), found.path + '/' + shown.file),
      copyButton('Copy where it is', 'Copied', found.path + '/' + shown.file, 'copy-file'));
  }
  if (shown.kind === 'link') {
    add(node, make('p', 'quiet', shown.file.split('/').pop() + ', ' + size(shown.size)
      + '. The deck itself is where this points:'));
  }
  add(node, window.TrainingStudioMarkdown.render(shown.text, { files: Boolean(found.files) }));
  if (shown.truncated) {
    add(node, make('p', 'quiet', 'This is the start of a long file of ' + size(shown.size)
      + '. Open the file for the rest.'));
  }
  return node;
}

// A file of a training as the server reads it out, in the shape a gate's document has.
function asDocument(read) {
  return { kind: read.binary ? 'file' : 'markdown', file: read.file, size: read.size,
    text: read.text, truncated: read.truncated };
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

// What is read at a gate: the document, with what changed in it one press away. A deck the
// runner rendered is its slides first, and which of them address each objective.
function reading(found) {
  const node = make('div', 'reading');
  if (slidesOf(found).length) add(node, slidesPart(found), coveragePart(found));
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

// What a Yoodli scenario was laid out from, to read beside it. It is read once for a gate.
async function readBeside(found, turn) {
  const named = found.beside;
  if (!named) {
    view.beside = null;
    return;
  }
  if (view.beside && view.beside.artifact === named.artifact) return;
  let held;
  try {
    held = { artifact: named.artifact,
      read: await ask('file', { path: found.path, artifact: named.artifact }) };
  } catch (failure) {
    held = { artifact: named.artifact, error: failure.message };
  }
  if (turn === view.turn) view.beside = held;
}

// It sits beside the document that is being decided, and never in its place.
function besidePart(found) {
  const named = found.beside;
  const held = view.beside && view.beside.artifact === named.artifact ? view.beside : null;
  const label = lower(named.label);
  const node = make('section', 'beside');
  node.setAttribute('aria-label', 'What it was laid out from');
  add(node, make('h2', 'aside-title', 'Laid out from ' + label),
    make('p', 'quiet', 'Here to compare with. What you are deciding is ' + lower(found.label)
      + ', not this.'));
  if (!held) return add(node, make('p', 'quiet', 'Reading it.'));
  if (held.error) {
    return add(node, callout('late', make('p', '', 'It could not be read. ' + held.error),
      make('p', 'quiet', 'Nothing was changed, and what you are deciding is not affected.'),
      add(make('div', 'bar'), button('Open it on its own', 'link', () => show('gate',
        { path: found.path, artifact: named.artifact }), 'beside ' + named.artifact))));
  }
  return add(node, documentBody(asDocument(held.read),
    { label: label.charAt(0).toUpperCase() + label.slice(1), path: found.path }));
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
  if (!passed && !failing && !found.audit) {
    return add(node, make('p', 'quiet', 'No automatic checks apply here. It is yours to read.'));
  }
  // While the review still finds something serious in a deck, nothing here says the deck is
  // through: the checks are said to have run, and what they do not look at is said too.
  if (passed && serious(found).length) {
    add(node, make('p', '', count(passed, 'automatic check', 'automatic checks')
      + ' ran and raised nothing. Automatic checks do not look at the slides: the review '
      + 'does, and it still finds something.'));
  } else if (passed) {
    add(node, state('done', count(passed, 'check', 'checks') + ' passed'));
  }
  if (failing) {
    add(node, make('p', 'quiet', count(failing, 'check', 'checks') + ' did not. See below.'));
  }
  return add(node, found.audit ? auditPart(found.audit) : null);
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
    make('p', 'quiet', runOf(found.path)
      ? 'It is being done on its own now, and comes back here for your review.'
      : 'Your assistant does this when you go back to the conversation.')));
  }
  if (items.childNodes.length) add(node, items);
  // A deck the runner rendered has its review as findings, shown in a part of their own.
  const note = typeof found.review === 'string' ? found.review : '';
  if (note) {
    const notes = make('details', 'review-notes');
    notes.dataset.key = 'review';
    // Open, except where two documents are read side by side below: there a long note
    // would push both off the first screen, so it waits to be opened.
    notes.open = !found.beside;
    add(notes, make('summary', '', 'The latest review note'),
      window.TrainingStudioMarkdown.render(note));
    add(node, notes);
  }
  if (!items.childNodes.length && !note) {
    add(node, make('p', 'quiet', reviewOf(found) ? 'Nothing else was flagged.'
      : 'Nothing was flagged.'));
  }
  return node;
}

function gateSignature(found) {
  return JSON.stringify([found.status, found.sha256, found.checked, found.out_of_date,
    found.review, found.asked, found.decisions, found.first, found.approval, found.stages,
    found.waiting, found.question, found.changes.same, found.changes.available,
    found.whose, found.beside, found.slides, found.audit, found.coverage]);
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
      + 'as it is.'), found.question ? make('p', 'quiet', asker(found.path)
      + found.question) : null);
  }
  if (list(found.first).length) {
    return callout('late', make('p', '', 'This cannot be approved yet. See “Worth a look”.'));
  }
  if (found.question) {
    return callout('yours', make('p', '', asker(found.path) + found.question));
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
  // A practice scenario says whose file it is: the person's own, or a draft made for them.
  // A deck the runner rendered says that its pictures are of the very file being decided.
  const decked = slidesOf(found).length > 0;
  if (!decked) view.viewer = null;
  const intro = add(make('div', 'intro'), state(words[0], words[1]),
    beads(found.stages, false),
    WHOSE[found.whose] ? make('p', 'lede', WHOSE[found.whose]) : null,
    decked ? make('p', 'lede', 'These are the slides themselves. The pictures were made from '
      + 'the very file you are deciding on.') : null);
  const aside = add(make('aside', 'aside'), reviewOf(found) ? findingsNote(found) : null,
    checkedNote(found), lookNote(found), changesNote(found.changes));
  aside.setAttribute('aria-label', 'The review');
  const above = [button(found.title, 'link', () => show(homeOf(found.path),
    { path: found.path }), 'training'),
  levelsText(found.levels) ? make('span', '', ' · ' + levelsText(found.levels)) : null];
  place({ title: found.label, name: found.label + ' · ' + found.title, above, back: true,
    actions: gateActions(found) },
  [intro, inChat(found), standing(found), add(make('div', found.beside ? 'gate gate-pair'
    : 'gate'), aside, reading(found), found.beside ? besidePart(found) : null)],
  fresh);
  tidyPictures();
  drawSheet();
}

// --- a gate: a deck's slides -----------------------------------------------------------
// A deck the runner rendered is shown as its slides: one at full size with the way to the
// next and the one before, and all of them in a strip to jump by. Beside them is what the
// review still finds, and under them which slides address each objective.

function slidesOf(found) {
  return list(found && found.slides);
}

// A deck's review as its findings, where the runner gives it that way.
function reviewOf(found) {
  return found.review && typeof found.review === 'object' ? found.review : null;
}

// The findings that matter most. While there is one, the page never says the deck is through.
function serious(found) {
  return list((reviewOf(found) || {}).findings)
    .filter((finding) => SERIOUS.includes(finding.severity));
}

function slideName(slide) {
  return 'Slide ' + slide.number + (slide.title ? ': ' + slide.title : '');
}

// Slides by their numbers: "slide 3", "slides 3 to 5", or "slides 3, 5 and 8".
function slidesNamed(numbers) {
  const held = list(numbers);
  if (held.length < 2) return held.length ? 'slide ' + held[0] : 'no slide';
  const row = held.length > 2 && held.every((number, index) => !index
    || number === held[index - 1] + 1);
  return 'slides ' + (row ? held[0] + ' to ' + held[held.length - 1]
    : series(held.map(String)));
}

function slidesPart(found) {
  const slides = slidesOf(found);
  const node = make('section', 'slides');
  node.id = 'slides';
  node.setAttribute('aria-label', 'The slides');
  if (!slides.some((slide) => slide.number === view.slide)) view.slide = slides[0].number;
  const at = () => slides.findIndex((slide) => slide.number === view.slide);
  const of = (slide) => ({ artifact: found.artifact, number: slide.number });
  const stage = make('div', 'paper stage');
  stage.id = 'slide-stage';
  stage.tabIndex = -1;
  stage.dataset.key = 'slide-stage';
  const now = make('p', 'slide-now');
  now.setAttribute('role', 'status');
  const earlier = capsule('Previous', '', () => view.viewer.move(-1), 'slide-previous');
  const later = capsule('Next', '', () => view.viewer.move(1), 'slide-next');
  earlier.setAttribute('aria-label', 'Previous slide');
  later.setAttribute('aria-label', 'Next slide');
  const strip = make('ol', 'strip');
  strip.setAttribute('aria-label', 'Every slide');
  const items = slides.map((slide) => {
    const item = button('', 'strip-item', () => view.viewer.go(slide.number),
      'slide ' + slide.number);
    item.setAttribute('aria-label', slideName(slide));
    add(strip, add(make('li'), add(item, pictureAt(of(slide), slideName(slide), found.sha256),
      make('span', 'strip-number', String(slide.number)),
      make('span', 'strip-title', slide.title || ''))));
    return item;
  });
  // Turning to a slide changes only what is in the stage, so nothing else loses its place.
  const turn = () => {
    const index = at();
    const slide = slides[index];
    // Where the focus was on what is about to go, it stays on the stage, not nowhere.
    const within = stage.contains(document.activeElement);
    stage.replaceChildren(pictureAt(of(slide), slideName(slide), found.sha256,
      { first: true, again: true }));
    if (within) stage.focus({ preventScroll: true });
    now.textContent = 'Slide ' + slide.number + ' of ' + slides.length
      + (slide.title ? ': ' + slide.title : '');
    // At either end the control stays where the keyboard can find it, and says it is off.
    earlier.setAttribute('aria-disabled', String(index === 0));
    later.setAttribute('aria-disabled', String(index === slides.length - 1));
    items.forEach((item, other) => {
      if (other === index) item.setAttribute('aria-current', 'true');
      else item.removeAttribute('aria-current');
    });
    // The strip follows the slide that is shown, sideways only: the page itself stays put.
    const shown = items[index].parentNode;
    const past = shown.offsetLeft + shown.offsetWidth - strip.clientWidth;
    if (shown.offsetLeft < strip.scrollLeft) strip.scrollLeft = shown.offsetLeft;
    else if (past > strip.scrollLeft) strip.scrollLeft = past;
  };
  view.viewer = {
    move(by) {
      const next = slides[at() + by];
      if (next) this.go(next.number);
    },
    go(number, look) {
      if (slides.some((slide) => slide.number === number)) {
        view.slide = number;
        turn();
      }
      // Reached from a finding, the slide itself is where the reader is taken.
      if (look) stage.focus();
    },
  };
  turn();
  return add(node, stage, add(make('div', 'bar slide-moves'), earlier, later, now), strip);
}

// What the reviewer still finds, the most serious first, in the reviewer's own words.
function findingsNote(found) {
  const review = reviewOf(found);
  const node = make('section', 'paper aside-part');
  add(node, make('h2', 'aside-title', 'What the review still finds'));
  const order = Object.keys(SEVERITIES);
  const rank = (finding) => (order.includes(finding.severity)
    ? order.indexOf(finding.severity) : order.length);
  const findings = list(review.findings).slice().sort((one, other) => rank(one) - rank(other)
    || one.number - other.number);
  // The reviewer drew none of the slides. How often it has looked says how far repair went.
  const looked = 'An independent reviewer, which drew none of the slides, has looked at each '
    + 'one' + (review.round > 0 ? ' ' + times(review.round) : '') + '.';
  if (!findings.length) {
    return add(node, make('p', '', 'The reviewer has nothing left to raise.'),
      make('p', 'quiet', looked + ' Whether the deck is good is still yours to judge.'));
  }
  const counted = order.map((severity) => [findings.filter((finding) => finding.severity
    === severity).length, SEVERITIES[severity][1].toLowerCase()])
    .filter(([number]) => number).map(([number, word]) => number + ' ' + word);
  const others = findings.filter((finding) => !SEVERITIES[finding.severity]).length;
  if (others) counted.push(others + (counted.length ? ' other' : ''));
  const says = series(counted) + (findings.length === 1 ? ' finding remains.'
    : ' findings remain.');
  add(node, serious(found).length ? state('late', says) : make('p', '', says),
    make('p', 'quiet', looked + ' The deck comes to you as it is.'));
  const items = make('ol', 'look findings');
  findings.forEach((finding, index) => {
    const [shape, words] = SEVERITIES[finding.severity]
      || ['none', spoken(finding.severity || 'finding')];
    const go = button('Slide ' + finding.number, 'link',
      () => view.viewer && view.viewer.go(finding.number, true), 'finding ' + index);
    add(items, add(make('li', 'finding'),
      add(make('p', 'foot-line'), state(shape, words), go,
        finding.about === 'content' ? make('span', 'tag', 'About what it says') : null),
      make('p', '', finding.note),
      finding.fix ? make('p', 'quiet', 'Suggested: ' + finding.fix) : null));
  });
  add(node, items);
  if (findings.some((finding) => finding.about === 'content')) {
    add(node, make('p', 'quiet', '“About what it says” is a finding about a slide’s words, '
      + 'not how it is drawn, so drawing the slide again would not put it right. Choose “Ask '
      + 'for changes” and say what should change: that leads back to what the deck says, and '
      + 'the slides are drawn from it again.'));
  }
  return node;
}

// What the brand's own check of the finished deck says. A warning is shown as a warning.
function auditPart(audit) {
  const warnings = list(audit.warnings);
  const node = add(make('div', 'audit'), make('h3', 'row-title', 'The brand’s own check'));
  if (!warnings.length) {
    const status = String(audit.status || '').toLowerCase();
    return add(node, AUDIT_QUIET.includes(status)
      ? state('done', 'It raised no warnings about the brand’s rules.')
      : state('none', 'It listed no warnings' + (status ? ', and answered “' + audit.status
        + '”.' : ', and did not say how it ended.')));
  }
  const items = make('ul', 'look');
  for (const warning of warnings) {
    const often = Number(warning.count) || 0;
    add(items, add(make('li'), state('late', 'Warning: ' + warning.says
      + (often > 1 ? ' (' + often + ' times)' : '')),
    warning.code ? add(make('p', 'quiet'), 'The brand’s name for it: ',
      make('code', '', warning.code)) : null));
  }
  return add(node, state('late', count(warnings.length, 'warning', 'warnings')), items,
    make('p', 'quiet', 'A warning does not stop the deck. It is here for you to weigh.'));
}

// Which slides address each objective: as the reviewer saw it, and as the deck itself says.
function coveragePart(found) {
  const rows = list(found.coverage);
  if (!rows.length) return null;
  const node = make('section', 'paper coverage');
  add(node, make('h2', 'aside-title', 'Which slides address each objective'),
    make('p', '', '“As reviewed” is where the reviewer, looking at the finished slides, found '
      + 'the objective addressed. “As cited” is where the deck itself says a slide serves it. '
      + 'Where the two differ, a slide may not do what it was written to do.'));
  const table = make('table', 'table');
  const head = make('tr');
  for (const title of ['Objective', 'As reviewed', 'As cited']) {
    const top = make('th', '', title);
    top.scope = 'col';
    head.append(top);
  }
  const body = make('tbody');
  const told = (numbers) => (list(numbers).length
    ? make('span', '', capital(slidesNamed(numbers))) : state('late', 'No slide'));
  for (const row of rows) {
    const name = make('th');
    name.scope = 'row';
    add(name, make('span', 'row-title', row.objective),
      row.says ? make('span', 'quiet', row.says) : null);
    add(body, add(make('tr'), name, cell('As reviewed', told(row.reviewed)),
      cell('As cited', told(row.cited))));
  }
  return add(node, add(table, add(make('thead'), head), body));
}

async function drawGate(fresh) {
  const turn = view.turn;
  if (fresh) {
    place({ title: 'Opening', back: true }, [make('p', 'quiet', 'Reading it.')], true);
  }
  try {
    const found = await ask('gate', { path: view.path, artifact: view.artifact });
    if (turn !== view.turn) return;
    await readBeside(found, turn);
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
  if (training.run) {
    // One driver for a training: what the page runs, the page decides.
    add(node, make('p', '', 'This training runs from this page, so each stage is approved '
      + 'here, by you. Nothing can approve it for you.'));
  } else {
    add(node, make('p', '', onPage
      ? 'Each stage is approved on this page. Your assistant cannot approve anything for you.'
      : 'Each stage is approved in your conversation with your assistant. You can move that '
        + 'here, so that only this page can approve.'),
    approvalControl(training.path, training.title || 'Untitled', training.approval,
      () => draw(false)));
  }
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
  const [shape, words] = standingOf(training);
  const waiting = training.waiting;
  const lead = waiting && waiting.artifact ? capsule('Review ' + waiting.label, 'filled',
    () => show('gate', { path: training.path, artifact: waiting.artifact }), 'lead') : null;
  // A training that runs on its own is watched on its run. This view keeps the detail.
  const watch = training.run ? capsule('Watch the run', '',
    () => show('run', { path: training.path }), 'watch') : null;
  place({ title: training.title || 'Untitled', above, back: true, actions: [watch, lead] },
    [add(make('div', 'intro'), state(shape, words), beads(training.stages, false),
      make('p', 'lede', saysOf(training))),
    filesCard(training),
    reasonsCard('In the way', training.view.blocking, 'Nothing is in the way.'),
    checksCard(training.check),
    reasonsCard('Left out or limited', training.view.limitations, 'Nothing was left out.'),
    reasonsCard('Warnings', training.view.warnings, 'No warnings.'),
    practiceCard(training), researchCard(training.status), guidanceCard(training.status),
    decisionsCard(training),
    // One driver for a training: while the page runs it, nobody is sent to an assistant.
    training.run && training.run.state !== 'done' ? null : folderCard(training)], fresh);
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

// --- with the runner behind the page ---------------------------------------------------
// Everything from here to "staying up to date" is offered only when the runner answers. On
// the plain desk `view.runner` is false, and none of it is ever shown or asked for.

// Ask, once, whether the runner is here. The plain desk answers 404, and that settles it.
async function discover() {
  try {
    const found = await ask('capabilities');
    view.runner = found.runner === true ? { version: String(found.version || '') } : false;
  } catch (failure) {
    if (failure.status === 404) view.runner = false;
    // No answer at all, or a link that is refused, is not an answer to this: it is asked again.
    else if (failure.kind !== 'failed') throw failure;
  }
}

// The runner is here and nobody has said where the trainings are kept. Until they have,
// set-up is the only screen there is.
function unset() {
  return Boolean(view.runner && view.setup && !view.setup.configured);
}

function frame() {
  const alone = unset();
  byId('sidebar').hidden = alone;
  if (alone) document.body.classList.add('alone');
  else document.body.classList.remove('alone');
}

// The run that is driving a training, or nothing where no run is.
function runOf(path) {
  const found = list(view.listing).find((training) => training.path === path);
  return (found && found.run) || null;
}

function homeOf(path) {
  return runOf(path) ? 'run' : 'training';
}

function asker(path) {
  return runOf(path) ? 'Training Studio asks: ' : 'Your assistant asks: ';
}

function runWords(run) {
  return RUN_WORDS[run.state] || RUN_WORDS.working;
}

// The run has made everything it can, and the one stage that is neither done nor left out is
// the deck's. The list does not say so itself, so it is read from the row of stages.
function deckLeft(training) {
  if (!training.run || training.run.state !== 'done' || training.state !== 'in-progress') {
    return false;
  }
  const open = list(training.stages).filter((stage) => stage.stage !== 'package'
    && !SETTLED.includes(stage.state));
  return open.length === 1 && open[0].stage === 'deck';
}

// Where a training stands, as a shape and words. A run knows more than the list does about
// one that is working, paused or stopped.
function standingOf(training) {
  if (deckLeft(training)) return STATES['in-progress'];
  if (training.run && (training.state === 'in-progress' || training.run.state === 'failed')) {
    return runWords(training.run);
  }
  return STATES[training.state] || STATES['in-progress'];
}

function newButton(kind) {
  return capsule('New training', kind, () => show('new'), 'new');
}

// The list says that a run needs its person. What it asks is read from the run itself.
async function readAsks() {
  const asking = view.listing.filter((training) => training.run
    && training.state === 'needs-you');
  const found = await Promise.all(asking.map((training) => ask('run', { path: training.path })
    .catch(() => null)));
  const asks = {};
  asking.forEach((training, index) => {
    const run = found[index];
    if (run && (run.question || run.problem || outlining(run))) {
      asks[training.path] = { question: run.question || null, problem: run.problem || null,
        outline: outlining(run) ? { level: run.outline.level || null } : null };
    }
  });
  view.asks = asks;
}

// A run that has put what a deck says to its person, and waits for the decision.
function outlining(run) {
  return Boolean(run.outline && run.outline.waiting);
}

// What a run asks is only that: to review what a deck says. A question or a problem of its
// own comes first, and is answered where it is asked.
function readsOutline(asked) {
  return Boolean(asked && asked.outline && !asked.question && !asked.problem);
}

// A question from a worker, with a box to answer in. What is typed is kept as it is typed.
function questionBox(path, title, question, kind, id) {
  const key = path + '\n' + question.id;
  const label = add(make('label', 'field-label', 'Your answer'),
    make('span', 'offscreen', ' for ' + title));
  label.htmlFor = id;
  const box = make('textarea', 'input');
  box.id = id;
  box.rows = 3;
  box.maxLength = 10000;
  box.value = view.answers[key] || '';
  box.dataset.key = 'answer ' + key;
  box.setAttribute('aria-describedby', id + '-problem');
  box.addEventListener('input', () => {
    view.answers[key] = box.value;
  });
  const problem = alertLine(id + '-problem');
  const go = capsule('Send answer', kind, () => sendAnswer(path, question, box, problem, go),
    'send ' + key);
  go.setAttribute('aria-label', 'Send answer for ' + title);
  return add(make('div', 'answer'),
    make('p', 'row-says', (question.from || 'A worker') + ' asks:'),
    make('p', 'row-quote', question.text), label, box, problem, add(make('div', 'bar'), go));
}

async function sendAnswer(path, question, box, problem, pressed) {
  const text = box.value.trim();
  if (!text) {
    // Refused here, beside the box, before anything is sent.
    say(problem, 'Write your answer first.');
    box.setAttribute('aria-invalid', 'true');
    box.focus();
    return;
  }
  if (view.busy) return;
  const turn = view.turn;
  view.busy = true;
  pressed.disabled = true;
  try {
    const run = await send('answer', { path, id: question.id, answer: text });
    delete view.answers[path + '\n' + question.id];
    delete view.asks[path];
    view.busy = false;
    toast('Your answer is sent. It carries on from here.');
    if (turn === view.turn && view.screen === 'run' && view.path === path) {
      // The question is gone from the screen: show the run from the top, as it now stands.
      view.run = run;
      paintRun(false);
      window.scrollTo(0, 0);
      byId('title').focus({ preventScroll: true });
    } else if (turn === view.turn && view.screen === 'home') {
      draw(false);
      byId('title').focus({ preventScroll: true });
    }
    refresh();
  } catch (failure) {
    say(problem, failure.message + ' Your answer is still here, and nothing was sent.');
    pressed.disabled = false;
  }
  view.busy = false;
}

// Whether the team can see the work yet, and the way to share it when they cannot.
function sharingLine() {
  const space = view.runner && view.setup ? view.setup.workspace : null;
  if (!space) return null;
  const node = make('p', 'foot-line');
  if (!space.repository) {
    return add(node, make('span', '', 'Your trainings are kept in a folder on this computer, '
      + 'and are not shared with anyone.'));
  }
  if (space.shared) {
    return add(node, state('done', 'Shared: your team can see everything decided so far.'));
  }
  add(node, state(space.notice ? 'late' : 'none', space.notice
    ? 'Not shared with your team yet. ' + space.notice
      + ' The work is kept on this computer until it is.'
    : 'Not shared with your team yet: the latest work is on this computer only.'));
  const go = capsule(view.sharing ? 'Sharing…' : 'Share now', '', shareNow, 'share');
  if (view.sharing) go.setAttribute('aria-busy', 'true');
  return add(node, go);
}

async function shareNow() {
  if (view.sharing) return;
  view.sharing = true;
  draw(false);
  let found;
  try {
    found = await send('share', {});
    toast(found.shared ? 'Shared. Your team can see it now.'
      : 'It is not shared yet. The work is still kept on this computer.');
  } catch (failure) {
    found = { shared: false, notice: failure.message };
    toast('It could not be shared. The work is still kept on this computer.');
  }
  // The set-up may have been read again meanwhile; the answer goes on the one that is held now.
  if (view.setup && view.setup.workspace) {
    view.setup.workspace.shared = Boolean(found.shared);
    view.setup.workspace.notice = found.notice || null;
  }
  view.sharing = false;
  draw(false);
  if (!focusKey('share')) byId('title').focus({ preventScroll: true });
}

function about(pairs) {
  const node = make('dl', 'about');
  for (const [name, value] of pairs) {
    if (given(value) && value !== '') add(node, make('dt', '', name), make('dd', '', value));
  }
  return node;
}

function limitsSays(limits) {
  const says = [];
  if (limits.step_seconds) says.push('A step may take up to ' + lasted(limits.step_seconds) + '.');
  if (given(limits.training_dollars)) {
    says.push('A training stops and asks you once it has spent '
      + money(limits.training_dollars) + '.');
  }
  if (limits.parallel) {
    says.push(limits.parallel === 1 ? 'One training runs at a time.'
      : 'Up to ' + limits.parallel + ' trainings run at once.');
  }
  return says.join(' ');
}

// Settings, with the runner: where the trainings are kept, who can see them, and the way in
// to change any of it.
function workspaceCard() {
  const held = view.runner ? view.setup : null;
  const space = held && held.workspace;
  if (!space) return null;
  const node = card('Workspace');
  const agent = held.agent || {};
  add(node, make('p', 'row-title', space.name || 'Your trainings'),
    about([[space.repository ? 'Repository' : 'Folder on this computer',
      space.repository || space.path],
    [space.repository ? 'This computer’s copy' : '', space.repository ? space.path : ''],
    ['Folder inside it', space.folder], ['Branch', space.branch],
    ['Shared', space.repository ? lower(SHARE_SAYS[space.share_when === 'when-asked' ? 1 : 0])
      : ''],
    ['Drafting is done by', (AGENT_NAMES[agent.default] || agent.default || 'no agent yet')
      + (agent.model ? ', with the model ' + agent.model : ', with the model it chooses itself')],
    ['Limits', limitsSays(held.limits || {})],
    ['Slide previews', held.previews ? previewsSays(held.previews) : '']]),
    sharingLine(),
    add(make('div', 'bar'), capsule('Change the set-up', '', () => show('setup'), 'setup')));
  return node;
}

// How previews are made, as it can be on this computer now: the way that was chosen, or
// else the first way there is, or nothing where there is none.
function previewsNow(found) {
  const can = PREVIEWS.filter((how) => found[how]);
  return can.includes(found.how) ? found.how : can[0] || null;
}

// How previews are made as it is set now, in a few words for Settings.
function previewsSays(found) {
  if (found.how) {
    return PREVIEW_WORDS[found.how] + (found[found.how] ? ''
      : ', which this computer cannot do now');
  }
  return found.drive || found.local ? 'not chosen yet: choose how in the set-up'
    : 'cannot be made on this computer yet';
}

// The preview files Training Studio made in the person's Drive. It never deletes one, so
// each is listed with where it is, for the person to remove.
function leftCard() {
  const found = view.runner && view.setup ? view.setup.previews : null;
  const left = list(found && found.left);
  if (!found || (!left.length && found.how !== 'drive')) return null;
  const node = card('Preview files in your Google Drive');
  add(node, make('p', '', 'A deck whose previews are made through Google Drive keeps one '
    + 'presentation there, named “Preview: …”. Training Studio never deletes one, so '
    + 'removing them is yours to do, in Drive, once a deck is finished.'));
  if (!left.length) return add(node, make('p', 'quiet', 'It has made none so far.'));
  const items = make('ul', 'rows');
  for (const file of left) {
    const text = add(make('div', 'row-text'), make('p', 'step-name', file.name),
      make('p', 'quiet', 'Made for ' + file.training));
    // Only a web address is a link to follow. Anything else is shown as the text it is.
    if (WEB_LINK.test(file.url || '')) {
      const go = make('a', 'link', 'Open it in Drive');
      go.href = file.url;
      go.rel = 'noopener noreferrer';
      go.target = '_blank';
      go.setAttribute('aria-label', 'Open ' + file.name + ' in Drive, in a new tab');
      add(text, add(make('p', ''), go));
    }
    add(items, add(make('li', 'row'), add(text, pathInto(make('p', 'path'), file.url || ''))));
  }
  return add(node, items);
}

// --- set-up ------------------------------------------------------------------------
// Shown first where nothing is set up yet, and from Settings afterwards. Each answer about
// where the trainings are kept is checked as it is given, and nothing is changed until Save.

function setupForm() {
  const held = view.setup;
  const space = held.workspace || {};
  const limits = held.limits || {};
  const agent = held.agent || {};
  const local = Boolean(held.workspace) && !space.repository;
  const seconds = Number(limits.step_seconds) || 0;
  return {
    where: local ? 1 : 0,
    repository: space.repository || '',
    path: local ? space.path || '' : '',
    folder: space.folder || '',
    branch: space.branch || '',
    name: space.name || '',
    touched: { folder: Boolean(space.folder), branch: Boolean(space.branch),
      name: Boolean(space.name) },
    share: space.share_when === 'when-asked' ? 1 : 0,
    agent: agent.default === 'codex' ? 'codex' : 'claude',
    model: agent.model || '',
    minutes: seconds ? String(Math.round(seconds / 6) / 10) : '', seconds,
    dollars: given(limits.training_dollars) ? String(limits.training_dollars) : '',
    parallel: given(limits.parallel) ? String(limits.parallel) : '',
    previews: previewsNow(held.previews || {}),
    check: null, checked: '', checking: false, unchecked: '', existing: false, turn: 0,
    saving: false,
  };
}

// What is asked of the check: exactly where the trainings would be kept, and nothing else.
// A folder or a branch that nobody has chosen is not asked about: the check says what it found.
function placeAsked(form) {
  const text = (value) => String(value).trim() || null;
  const chosen = (name) => (form.touched[name] || form.existing ? text(form[name]) : null);
  return { repository: form.where ? null : text(form.repository),
    path: form.where ? text(form.path) : null,
    folder: chosen('folder'), branch: chosen('branch') };
}

// A different place was named. What was found in the last one says nothing about this one.
function forgetFound(form) {
  for (const name of ['folder', 'branch', 'name']) {
    if (!form.existing && form.touched[name]) continue;
    form[name] = '';
    form.touched[name] = false;
  }
  form.existing = false;
  form.check = null;
}

function checkItem(found) {
  const item = add(make('li', 'check-item'), add(make('p', 'fact'),
    bead(found.ok ? 'done' : 'late'),
    make('span', '', found.what + (found.ok ? ': yes' : ': no'))));
  if (!found.ok && found.fix) add(item, make('p', 'fix', found.fix));
  return item;
}

function paintChecks() {
  const form = view.form;
  const holder = byId('setup-checks');
  if (!form || !holder) return;
  const nodes = [];
  if (form.checking) {
    nodes.push(make('p', 'quiet', 'Checking…'));
  } else if (form.unchecked) {
    nodes.push(make('p', 'problem', 'This could not be checked. ' + form.unchecked),
      make('p', 'quiet', 'Nothing was changed. Try “Check again”.'));
  } else if (form.check) {
    const checks = list(form.check.checks);
    const wrong = checks.filter((found) => !found.ok).length;
    const items = make('ul', 'plain check-items');
    for (const found of checks) items.append(checkItem(found));
    nodes.push(items, form.check.ok
      ? state('done', 'This is ready to use.')
      : state('late', (wrong ? count(wrong, 'thing needs', 'things need') : 'Something needs')
        + ' putting right before this can be saved. Then choose “Check again”.'));
  } else {
    nodes.push(make('p', 'quiet', form.where
      ? 'It is checked as soon as you say which folder.'
      : 'It is checked as soon as you give the address.'));
  }
  holder.replaceChildren(...nodes);
}

// What the check found is filled in. Where the team has already set Training Studio up in
// the repository, its folder, branch and name are theirs, and are not asked for again.
function fillFound(found) {
  const form = view.form;
  form.existing = Boolean(found.existing);
  for (const name of ['folder', 'branch', 'name']) {
    const box = byId('setup-' + name);
    if (found[name] && (form.existing || !form.touched[name])) form[name] = String(found[name]);
    if (!box) continue;
    box.value = form[name];
    box.readOnly = form.existing;
  }
  const note = byId('setup-found');
  if (!note) return;
  note.hidden = !form.existing;
  note.replaceChildren(...(form.existing ? [make('p', '', 'Training Studio is already set up '
    + 'in this repository' + (found.name ? ', as “' + found.name + '”' : '') + '. Its folder, '
    + 'branch and name are read from the hub.json your team keeps there, so there is nothing '
    + 'to choose here.')] : []));
}

async function checkSetup() {
  const form = view.form;
  const asked = placeAsked(form);
  form.turn += 1;
  const turn = form.turn;
  form.unchecked = '';
  if (!asked.repository && !asked.path) {
    form.check = null;
    form.checking = false;
    fillFound({});
    paintChecks();
    return false;
  }
  form.checking = true;
  paintChecks();
  try {
    const found = await send('setup/check', asked);
    if (view.form !== form || turn !== form.turn) return false;
    form.check = found;
    fillFound(found.found || {});
  } catch (failure) {
    if (view.form !== form || turn !== form.turn) return false;
    form.check = null;
    form.unchecked = failure.message;
  }
  form.checked = JSON.stringify(placeAsked(form));
  form.checking = false;
  paintChecks();
  return Boolean(form.check && form.check.ok);
}

// An agent, as the runner found it: installed, signed in, reachable from this network.
function agentItem(found) {
  const yes = (value, unknown) => (value === true ? ['ok', ''] : value === false
    ? ['problem', 'no'] : ['unknown', unknown]);
  const facts = [{ label: 'Installed', state: found.installed ? 'ok' : 'problem',
    detail: found.installed ? found.version || '' : 'not found' }];
  if (found.installed) {
    const [signed, signedSays] = yes(found.signed_in, 'cannot be asked');
    const [reached, reachedSays] = yes(found.reachable, 'not known');
    facts.push({ label: 'Signed in', state: signed, detail: signedSays },
      { label: 'Reachable from this network', state: reached, detail: reachedSays });
  }
  const usable = found.installed && found.signed_in !== false && found.reachable !== false
    && !found.problem;
  return computerItem({ name: AGENT_NAMES[found.agent] || found.agent,
    state: usable ? 'ok' : found.installed ? 'problem' : 'missing', facts,
    fix: found.problem || '' });
}

function paintAgents() {
  const holder = byId('agents');
  if (!holder) return;
  const nodes = [];
  if (view.looking && !view.agents) {
    nodes.push(make('p', 'quiet', 'Looking for the agents on this computer…'));
  } else if (view.unlooked) {
    nodes.push(make('p', 'problem', 'The agents could not be looked for. ' + view.unlooked),
      make('p', 'quiet', 'Nothing was changed. Try “Look again”.'));
  } else if (view.agents) {
    const items = make('ul', 'computer-items');
    for (const found of view.agents) items.append(agentItem(found));
    nodes.push(items);
    if (!view.agents.length) {
      nodes.push(make('p', 'problem', 'No agent was found on this computer. Install Claude '
        + 'Code or Codex, sign in to it, then choose “Look again”.'));
    }
  }
  holder.replaceChildren(...nodes);
}

async function readAgents() {
  if (view.looking) return;
  view.looking = true;
  paintAgents();
  try {
    view.agents = list((await ask('agents')).agents);
    view.unlooked = '';
  } catch (failure) {
    view.unlooked = failure.message;
  }
  view.looking = false;
  paintAgents();
}

// Which agent, and which of its models. The same two questions are asked at set-up, for the
// default, and at the last step of a new training, for that training.
function agentFields(held, prefix, label) {
  const found = make('div', 'agents');
  found.id = 'agents';
  found.setAttribute('role', 'status');
  return [found,
    add(make('div', 'bar'), capsule('Look again', 'quiet', readAgents, 'agents-again')),
    choice(label, AGENTS.map((name) => AGENT_NAMES[name]), AGENTS.indexOf(held.agent),
      (index) => {
        held.agent = AGENTS[index];
      }, prefix + '-agent'),
    field(prefix + '-model', 'Its model (optional)', held, 'model', { hint: 'Leave this empty '
      + 'to use the model the agent chooses for itself.' })];
}

function placeCard(form) {
  const node = card('Where your trainings are kept');
  const again = () => {
    checkSetup();
  };
  const moved = () => {
    forgetFound(form);
    checkSetup();
  };
  add(node, choice('Kept in', ['A team repository', 'A folder on this computer'], form.where,
    (index) => {
      form.where = index;
      forgetFound(form);
      paintSetup(false);
      checkSetup();
    }, 'where'));
  if (form.where) {
    add(node, field('setup-path', 'The folder', form, 'path', { changed: moved,
      hint: 'A folder on this computer, for trying things out. Nothing in it is shared with '
        + 'anyone.' }));
  } else {
    add(node, field('setup-repository', 'The repository’s address', form, 'repository', {
      changed: moved,
      hint: 'The address you would clone it from. Training Studio keeps a copy of its own on '
        + 'this computer, and writes inside one folder of the repository and nowhere else.' }));
  }
  const found = make('div', 'paper callout');
  found.id = 'setup-found';
  found.hidden = true;
  const touch = (name) => () => {
    form.touched[name] = true;
  };
  add(node, found,
    field('setup-folder', 'The folder inside it', form, 'folder', { changed: again,
      typed: touch('folder'), hint: 'Everything Training Studio writes goes in this folder.' }),
    field('setup-branch', 'The branch', form, 'branch', { changed: again,
      typed: touch('branch') }),
    field('setup-name', 'A name for this workspace', form, 'name', { typed: touch('name'),
      hint: 'What your team calls this collection of trainings: a short name with no '
        + 'spaces, such as field-training.' }));
  const checks = make('div', 'checks');
  checks.id = 'setup-checks';
  checks.setAttribute('role', 'status');
  return add(node, make('h3', 'row-title', 'Checked for you'), checks,
    add(make('div', 'bar'), capsule('Check again', 'quiet', again, 'check-again')));
}

function shareCard(form) {
  return add(card('When your team sees the work'), ...explained('Share',
    ['After each decision', 'Only when I ask'], SHARE_SAYS, form.share, (index) => {
      form.share = index;
    }, 'share-when'));
}

function limitsCard(form) {
  const node = card('Limits');
  return add(node, make('p', '', 'These keep a training from running away with your time or '
    + 'your money. A training that reaches one stops and asks you.'),
  field('setup-minutes', 'The longest a step may take, in minutes', form, 'minutes',
    { short: true, mode: 'decimal' }),
  field('setup-dollars', 'The most a training may spend, in dollars', form, 'dollars',
    { short: true, mode: 'decimal', hint: 'Counted where the agent says what it spends.' }),
  field('setup-parallel', 'How many trainings may run at once', form, 'parallel',
    { short: true, mode: 'numeric' }));
}

// How the pictures of a deck's slides are made. Each way says what it means, and a way this
// computer cannot do says so and cannot be chosen.
function previewsCard(form) {
  const found = view.setup.previews;
  if (!found) return null;
  const node = card('How slide previews are made');
  add(node, make('p', '', 'While a slide deck is drawn, each slide is turned into a picture, '
    + 'so that it can be looked at and put right before it comes to you. A deck cannot be '
    + 'made without them.'));
  if (!form.previews) {
    return add(node, state('late', 'This computer cannot make them yet.'),
      make('p', 'fix', 'It needs LibreOffice, or Google access that reaches Drive. Everything '
        + 'but the deck can be made meanwhile, and the Status screen says what a deck needs.'));
  }
  const [control, meanings] = explained('Make them with', PREVIEW_NAMES, PREVIEW_SAYS,
    PREVIEWS.indexOf(form.previews), (index) => {
      form.previews = PREVIEWS[index];
    }, 'previews');
  add(node, control, meanings);
  PREVIEWS.forEach((how, index) => {
    if (found[how]) return;
    const option = control.querySelectorAll('.seg-option')[index];
    option.disabled = true;
    option.classList.add('seg-absent');
    add(node, make('p', 'fix', PREVIEW_ABSENT[index]));
  });
  if (found.how && found.how !== form.previews) {
    add(node, make('p', 'problem', PREVIEW_NAMES[PREVIEWS.indexOf(found.how)] + ' was chosen '
      + 'before, and this computer cannot use it now. Save to use the other way.'));
  }
  return node;
}

function paintSetup(fresh) {
  const form = view.form;
  const first = !view.setup.configured;
  view.drawn = 'setup';
  const problem = alertLine('setup-problem');
  const save = capsule(first ? 'Save and go on' : 'Save', 'filled', () => saveSetup(save),
    'save');
  const intro = add(make('div', 'intro'),
    first ? make('p', 'large-title', 'Welcome. Let’s get you set up.') : null,
    make('p', 'lede', 'Say where your team keeps its trainings and which agent does the '
      + 'drafting. Each answer is checked as you give it, and nothing is changed until you '
      + 'save.' + (first ? ' Then you can start your first training.' : '')));
  const body = add(make('div', 'narrow'), intro, placeCard(form),
    form.where ? null : shareCard(form),
    add(card('The agent that does the drafting'),
      make('p', '', 'An agent is the AI that drafts each stage for you to decide on. It has '
        + 'to be installed on this computer and signed in.'),
      ...agentFields(form, 'setup', 'Use by default')),
    previewsCard(form), limitsCard(form),
    add(make('div', 'form-foot'), problem, add(make('div', 'bar'), save,
      first ? null : capsule('Cancel', 'quiet', back, 'cancel'))));
  place({ title: first ? 'Set up Training Studio' : 'Set-up', name: 'Set-up',
    above: first ? [] : [make('span', '', 'Settings')], back: !first }, [body], fresh);
  fillFound((form.check && form.check.found) || (form.existing ? { existing: true } : {}));
  paintChecks();
  paintAgents();
}

function drawSetup(fresh) {
  if (!fresh && view.drawn === 'setup') return;
  if (!view.form) view.form = setupForm();
  paintSetup(true);
  checkSetup();
  readAgents();
}

// A limit as a number, or nothing when what was typed is not one that can be used.
function limit(id, text, whole) {
  const value = Number(String(text).trim());
  const fine = String(text).trim() !== '' && Number.isFinite(value) && value > 0
    && (!whole || Number.isInteger(value));
  refuse(id, fine ? '' : whole ? 'Give a whole number, 1 or more.'
    : 'Give a number greater than 0.');
  return fine ? value : null;
}

async function saveSetup(pressed) {
  const form = view.form;
  if (form.saving) return;
  const problem = byId('setup-problem');
  say(problem, '');
  const asked = placeAsked(form);
  const where = form.where ? 'setup-path' : 'setup-repository';
  const missing = [];
  const need = (id, value, text) => {
    if (!refuse(id, value ? '' : text).getAttribute('aria-invalid')) return;
    missing.push(id);
  };
  need(where, asked.repository || asked.path, form.where ? 'Say which folder first.'
    : 'Give the repository’s address first.');
  const minutes = limit('setup-minutes', form.minutes, false);
  const dollars = limit('setup-dollars', form.dollars, false);
  const parallel = limit('setup-parallel', form.parallel, true);
  for (const [id, value] of [['setup-minutes', minutes], ['setup-dollars', dollars],
    ['setup-parallel', parallel]]) {
    if (value === null) missing.push(id);
  }
  if (missing.length) {
    say(problem, 'Something above is missing. Nothing was saved.');
    byId(missing[0]).focus();
    return;
  }
  form.saving = true;
  pressed.disabled = true;
  const done = (text) => {
    form.saving = false;
    pressed.disabled = false;
    say(problem, text);
    if (text) pressed.focus();
  };
  // Never save a place that has not been checked as it now stands.
  if (form.checking || !form.check || form.checked !== JSON.stringify(asked)) await checkSetup();
  if (view.form !== form) return;
  if (!form.check || !form.check.ok) {
    done('Where your trainings are kept needs putting right first: see “Checked for you” '
      + 'above. Nothing was saved.');
    return;
  }
  for (const [name, text] of [['folder', 'Say which folder inside it.'],
    ['branch', 'Say which branch.'], ['name', 'Give it a name.']]) {
    need('setup-' + name, form[name].trim(), text);
  }
  // What the repository already says is taken as it is. What was typed here has to be plain.
  for (const name of form.existing ? [] : ['folder', 'name']) {
    const id = 'setup-' + name;
    if (missing.includes(id) || PLAIN_NAME.test(form[name].trim())) continue;
    refuse(id, PLAIN_SAYS);
    missing.push(id);
  }
  if (missing.length) {
    done('Something above is missing or cannot be used. Nothing was saved.');
    byId(missing[0]).focus();
    return;
  }
  // Minutes are shown to the nearest tenth. A time nobody changed is saved as it was.
  const kept = form.seconds && minutes === Math.round(form.seconds / 6) / 10;
  const body = { folder: form.folder.trim(), branch: form.branch.trim(),
    name: form.name.trim(), share_when: form.where ? SHARE[1] : SHARE[form.share],
    agent: form.agent, model: form.model.trim() || null,
    limits: { step_seconds: kept ? form.seconds : Math.max(1, Math.round(minutes * 60)),
      training_dollars: dollars, parallel } };
  if (form.where) body.path = asked.path;
  else body.repository = asked.repository;
  // Where this computer can make previews in neither way, there is no choice to send.
  if (form.previews) body.previews = form.previews;
  const first = !view.setup.configured;
  try {
    view.setup = await send('setup', body);
  } catch (failure) {
    done(failure.message + ' Nothing was saved, and your answers are still here: change what '
      + 'it names and save again.');
    return;
  }
  form.saving = false;
  frame();
  toast(first ? 'You are set up. Now start your first training.' : 'The set-up is saved.');
  if (first || view.pushed === 0) show(first ? 'home' : 'settings', null, true);
  else back();
}

// --- a new training ------------------------------------------------------------------
// Three short steps, with a default for every choice. Nothing is sent until the last one.

function newDraft() {
  const agent = (view.setup && view.setup.agent) || {};
  return settleDeck({ step: 0, title: '', topic: '', audience: '', purpose: 0,
    levels: ['101'], brief: 0, time: '', deck: 0, brand: '', variant: '', copies: [],
    yoodli: false, sources: 0, agent: agent.default === 'codex' ? 'codex' : 'claude',
    model: agent.model || '', starting: false });
}

// The brands a deck can be made in, as the brand skill on this computer lists them. A deck
// is always made in one, so with none there is no deck to choose.
function brandsFound() {
  const found = (view.setup && view.setup.brand) || {};
  return found.found ? list(found.brands) : [];
}

// Hold a draft to what this computer can do now: a brand the brand skill has, one of that
// brand's variants, and no deck where no brand is to be had.
function settleDeck(draft) {
  const brands = brandsFound();
  const chosen = brands.find((brand) => brand.brand === draft.brand) || brands[0];
  const variants = list(chosen && chosen.variants);
  draft.brand = chosen ? chosen.brand : '';
  draft.variant = variants.includes(draft.variant) ? draft.variant : variants[0] || '';
  if (!chosen) draft.deck = DECKS.length - 1;
  return draft;
}

// The fewest times a training stops for a decision: at its questions, at its research, and at
// the blueprint, the guide and the brief of each level. Each practice scenario asks once more,
// and how many there are is not known until a blueprint names them. The runner says the same
// number back once it has started.
function gatesFor(draft) {
  return 2 + 3 * Math.max(1, draft.levels.length);
}

function times(number) {
  return number === 1 ? 'once' : number === 2 ? 'twice' : number + ' times';
}

function chips(label, options, chosen, flip, key, hint) {
  const row = make('div', 'chips');
  row.setAttribute('role', 'group');
  row.setAttribute('aria-label', label);
  for (const [value, text] of options) {
    row.append(chip(text, chosen(value), (on) => flip(value, on), key + ' ' + value));
  }
  return add(make('div', 'field'), make('p', 'field-label', label), row,
    hint ? make('p', 'quiet field-hint', hint) : null);
}

function topicStep(draft) {
  return [add(card('About it'),
    field('new-title', 'A short title', draft, 'title',
      { hint: 'What it is called in every list, for example “Rolling restarts”.' }),
    field('new-topic', 'What should it teach?', draft, 'topic', { long: true,
      hint: 'A sentence or two is enough. The research questions are drafted from this.' }),
    field('new-audience', 'Who is it for?', draft, 'audience', { long: true,
      hint: 'Their role, and what they already know.' }),
    choice('What it is for', PURPOSES, draft.purpose, (index) => {
      draft.purpose = index;
    }, 'purpose'))];
}

// One thing chosen from several, in the browser's own list. Where there is only one, there
// is nothing to choose, and it is said in a line.
function oneOf(id, label, options, held, name, changed) {
  if (options.length > 1) return field(id, label, held, name, { options, changed });
  return add(make('div', 'field'), make('p', 'field-label', label),
    make('p', '', options.length ? options[0][1] : 'None'));
}

// The brand a deck is made in, and which of its variants: both as the brand skill on this
// computer lists them. Choosing another brand offers that brand's variants.
function brandFields(draft) {
  const found = (view.setup && view.setup.brand) || {};
  const brands = brandsFound();
  const node = make('div', 'fields');
  const fill = () => {
    const chosen = brands.find((brand) => brand.brand === draft.brand) || {};
    const variants = list(chosen.variants);
    node.replaceChildren();
    add(node, oneOf('new-brand', 'The deck’s brand',
      brands.map((brand) => [brand.brand, brand.name || brand.brand]), draft, 'brand', () => {
        settleDeck(draft);
        fill();
        focusKey('new-brand');
      }),
    variants.length ? oneOf('new-variant', 'The brand’s variant',
      variants.map((variant) => [variant, variant]), draft, 'variant') : null,
    make('p', 'quiet field-hint', 'A deck is always made in a brand. '
      + (found.name ? 'These are what ' + found.name + ', the brand skill on this computer, '
        + 'offers.' : 'These are what the brand skill on this computer offers.')),
    found.problem ? make('p', 'fix', found.problem) : null);
  };
  fill();
  return node;
}

function shapeStep(draft) {
  const toggle = (held) => (value, on) => {
    draft[held] = draft[held].filter((other) => other !== value);
    if (on) draft[held].push(value);
  };
  settleDeck(draft);
  const able = brandsFound().length > 0;
  const found = (view.setup && view.setup.brand) || {};
  const brand = able ? brandFields(draft) : make('p', 'fix', 'A slide deck cannot be made on '
    + 'this computer. ' + (found.problem || 'No brand skill was found on it, and a deck is '
    + 'always made in a brand.') + ' Everything else is made as usual, and the Status screen '
    + 'says what a deck needs.');
  brand.hidden = able && DECKS[draft.deck][0] === null;
  const deck = choice('The slide deck', DECKS.map((kind) => kind[1]), draft.deck, (index) => {
    draft.deck = index;
    brand.hidden = DECKS[index][0] === null;
  }, 'deck');
  // With no brand to make one in, "No deck" is what is chosen, and the others cannot be.
  for (const option of able ? [] : deck.querySelectorAll('.seg-option[aria-pressed="false"]')) {
    option.disabled = true;
    option.classList.add('seg-absent');
  }
  return [add(card('The choices'),
    make('p', '', 'Every choice here has an answer already. Change only what you want to.'),
    chips('Levels', LEVELS.map((level) => [level, level]),
      (level) => draft.levels.includes(level), toggle('levels'), 'level',
      'Each level is a depth of the same subject: 101 is the introduction, 401 the deepest. '
        + 'Each gets a blueprint of its own. Choose none for one training without levels; '
        + 'levels cannot be added to that later.'),
    choice('What the brief is about', ['One product or technology', 'A comparison'],
      draft.brief, (index) => {
        draft.brief = index;
      }, 'brief'),
    field('new-time', 'How long it should take (optional)', draft, 'time',
      { hint: 'In your own words: “30 minutes”, “one lesson”, “a full course”.' }),
    deck, brand,
    chips('Keep a copy of each guide and brief', COPIES,
      (kind) => draft.copies.includes(kind), toggle('copies'), 'copy',
      'Neither is needed. The training keeps its own files either way.'),
    chips('Practice', [['yoodli', 'Make scenarios for Yoodli']], () => draft.yoodli,
      (value, on) => {
        draft.yoodli = on;
      }, 'practice', 'Off unless your team practises in Yoodli.'))];
}

function startStep(draft) {
  const limits = (view.setup && view.setup.limits) || {};
  const levels = draft.levels.length;
  const asks = gatesFor(draft);
  // With documents of your own, the first thing it does is wait for them.
  const first = make('p', '', 'First it waits for your documents. You add them on the next '
    + 'screen, and nothing is researched until you say that is all of them.');
  const then = make('p', '');
  const tell = () => {
    const supplied = SOURCES[draft.sources][0] !== 'public-web';
    first.hidden = !supplied;
    then.textContent = (supplied ? 'Then it works' : 'It starts at once and works')
      + ' on its own. It stops and asks for your decision at least ' + times(asks)
      + ': at the research questions, at the research, and at the blueprint, the learner '
      + 'guide and the brief' + (levels > 1 ? ' of each of the ' + levels + ' levels.' : '.');
  };
  tell();
  return [add(card('Sources'), ...explained('Where the research looks',
    SOURCES.map((source) => source[1]), SOURCE_SAYS, draft.sources, (index) => {
      draft.sources = index;
      tell();
    }, 'sources')),
  add(card('The agent that does the drafting'), ...agentFields(draft, 'new', 'For this training')),
  add(card('Limits'), make('p', '', limitsSays(limits)
    || 'No limits are set for this computer.'),
  make('p', 'quiet', 'A training that reaches a limit stops and asks you. The limits are '
    + 'changed in Settings.')),
  add(make('div', 'paper callout'),
    make('h2', 'aside-title', 'What happens when you start'), first, then,
    make('p', '', 'It asks once more for each practice scenario' + (draft.yoodli
      ? ', and again for each one laid out for Yoodli' : '') + '. How many there are is not '
      + 'known until a blueprint names them.'),
    // A deck has two decisions of its own: what it says, and then the slides themselves.
    DECKS[draft.deck][0] ? make('p', '', 'For the slide deck' + (levels > 1 ? ' of each level'
      : '') + ' it asks twice more: once for what the deck says, before any slide is drawn, '
      + 'and once for the deck itself.') : null,
    make('p', 'quiet', 'This page tells you each time. In between, you can close it.'))];
}

function paintNew(fresh) {
  const draft = view.draft;
  view.drawn = 'new';
  const builders = [topicStep, shapeStep, startStep];
  const problem = alertLine('new-problem');
  const last = draft.step === STEPS.length - 1;
  const go = capsule(last ? 'Start the training' : 'Continue', 'filled',
    () => (last ? startTraining(go) : nextStep()), 'continue');
  const earlier = draft.step ? capsule('Back a step', 'quiet', () => {
    draft.step -= 1;
    paintNew(true);
  }, 'earlier') : null;
  const body = add(make('div', 'narrow'), ...builders[draft.step](draft),
    add(make('div', 'form-foot'), problem, add(make('div', 'bar'), go, earlier)));
  place({ title: STEPS[draft.step], name: 'New training', back: true,
    above: [make('span', '', 'New training · Step ' + (draft.step + 1) + ' of ' + STEPS.length)] },
  [body], fresh);
  if (last) paintAgents();
}

function drawNew(fresh) {
  if (!fresh && view.drawn === 'new') return;
  if (!view.draft) view.draft = newDraft();
  paintNew(true);
  if (view.draft.step === STEPS.length - 1) readAgents();
}

function nextStep() {
  const draft = view.draft;
  if (draft.step === 0) {
    const missing = [['new-title', draft.title, 'Give it a title first.'],
      ['new-topic', draft.topic, 'Say what it should teach first.'],
      ['new-audience', draft.audience, 'Say who it is for first.']]
      .filter(([id, value, text]) => refuse(id, value.trim() ? '' : text)
        .getAttribute('aria-invalid'));
    say(byId('new-problem'), missing.length ? 'Something above is missing.' : '');
    if (missing.length) {
      byId(missing[0][0]).focus();
      return;
    }
  }
  draft.step += 1;
  paintNew(true);
  if (draft.step === STEPS.length - 1) readAgents();
}

async function startTraining(pressed) {
  const draft = view.draft;
  if (draft.starting) return;
  const problem = byId('new-problem');
  const deck = DECKS[settleDeck(draft).deck][0];
  const body = {
    title: draft.title.trim(), topic: draft.topic.trim(), audience: draft.audience.trim(),
    purpose: PURPOSES[draft.purpose],
    levels: LEVELS.filter((level) => draft.levels.includes(level)),
    brief_kind: draft.brief ? 'competitive' : 'product',
    time_limit: draft.time.trim() || null,
    source_scope: SOURCES[draft.sources][0],
    deck_target: deck,
    brand: deck ? { brand: draft.brand, variant: draft.variant || null } : null,
    copies: COPIES.map((kind) => kind[0]).filter((kind) => draft.copies.includes(kind)),
    yoodli: draft.yoodli,
    agent: draft.agent, model: draft.model.trim() || null,
  };
  draft.starting = true;
  pressed.disabled = true;
  say(problem, '');
  let started;
  try {
    started = await send('trainings', body);
  } catch (failure) {
    draft.starting = false;
    pressed.disabled = false;
    say(problem, failure.message + (failure.kind === 'stopped' ? ''
      : ' Nothing was started.') + ' Your answers are still here.');
    pressed.focus();
    return;
  }
  view.draft = null;
  view.promised = { path: started.path, gates: Number(started.gates) || 0 };
  toast(body.source_scope === 'public-web' ? 'Started. It is working on its own now.'
    : 'Started. It waits for your documents first.');
  show('run', { path: started.path }, true);
  refresh();
}

// --- a run -------------------------------------------------------------------------
// One training working on its own: where it is, what it is doing, what it has made and
// spent, and the three controls. It is drawn in parts, and a part that has not changed is
// left exactly as it is, so an answer being written stays under the cursor while the rest
// of the screen keeps up with the run.

function placeParts(spec, parts, fresh) {
  const holder = main();
  const active = document.activeElement;
  const focused = !fresh && active && active.dataset ? active.dataset.key : '';
  const opened = fresh ? [] : Array.from(holder.querySelectorAll('details'))
    .filter((node) => node.open).map((node) => node.dataset.key);
  const bar = JSON.stringify(spec.mark);
  if (fresh || bar !== view.barred) toolbar(spec);
  view.barred = bar;
  const kept = new Map();
  for (const node of fresh ? [] : Array.from(holder.children)) {
    if (PARTS.has(node)) kept.set(PARTS.get(node), node);
  }
  const nodes = [];
  for (const [name, from, build] of parts.filter(Boolean)) {
    const mark = name + '\n' + JSON.stringify(from);
    let node = kept.get(mark);
    if (!node) {
      node = build();
      PARTS.set(node, mark);
    }
    nodes.push(node);
  }
  let at = holder.firstChild;
  for (const node of nodes) {
    if (node === at) at = at.nextSibling;
    else holder.insertBefore(node, at);
  }
  while (at) {
    const next = at.nextSibling;
    at.remove();
    at = next;
  }
  for (const node of holder.querySelectorAll('details')) {
    if (opened.includes(node.dataset.key)) node.open = true;
  }
  if (fresh) {
    window.scrollTo(0, 0);
    byId('title').focus({ preventScroll: true });
  } else if (focused && !document.body.contains(active) && !focusKey(focused)) {
    byId('title').focus({ preventScroll: true });
  }
}

// The next decision a run will ask for, so the person knows what is coming.
function nextGate(run) {
  return list(run.steps).find((step) => step.kind === 'gate' && step.status === 'to-do') || null;
}

// A run that waits for documents waits for its person, whatever it says of itself meanwhile.
function adding(run) {
  return Boolean(run.documents && run.documents.waiting);
}

// A run that is done has finished the training, or has made everything but the deck.
function runStanding(run) {
  if (run.finished) {
    return run.finished.ready ? ['done', 'Finished']
      : ['late', 'Finished, but not ready to use'];
  }
  if (run.deck_left) return ['done', 'Everything but the slide deck is made'];
  return run.state === 'working' && (adding(run) || outlining(run)) ? RUN_WORDS.waiting
    : runWords(run);
}

function runIntro(run, training, promised) {
  const node = add(make('div', 'intro'), state(...runStanding(run)));
  if (list(training.stages).length) add(node, beads(training.stages, false));
  add(node, make('p', 'lede run-says', run.sentence));
  const next = nextGate(run);
  if (run.state === 'working' && !adding(run) && !outlining(run)) {
    add(node, make('p', 'quiet', 'Nothing is needed from you right now. It carries on by '
      + 'itself, and this page tells you when it needs you.'
      + (next ? ' Next it asks for your decision on '
        + lower(next.label).replace(/^your review of /, '') + '.' : '')));
  } else if (run.state === 'paused') {
    add(node, make('p', 'quiet', 'Nothing more is started until you resume it. Everything '
      + 'made so far is kept.'));
  } else if (run.state === 'stopped' && !run.problem) {
    add(node, make('p', 'quiet', 'Everything made so far is kept. Resume, and it carries on '
      + 'from where it stopped.'));
  }
  if (promised && run.state !== 'done') {
    add(node, make('p', 'quiet', 'In all, it stops and asks for your decision at least '
      + times(promised) + '.'));
  }
  if (view.steered) {
    const problem = make('p', 'problem', view.steered);
    problem.setAttribute('role', 'alert');
    add(node, problem);
  }
  return node;
}

// What went wrong, what was kept, and the one thing to do about it.
function problemPart(run, lead) {
  const found = run.problem;
  const label = found.label || (found.action === 'retry' ? 'Try again' : 'Resume');
  const go = found.action
    ? capsule(label, lead ? 'filled' : '', () => steer(found.action, go), 'problem-action')
    : capsule('See everything it made', '', () => show('training', { path: view.path }),
      'problem-open');
  return callout('late', make('h2', 'aside-title', 'It has stopped, and needs you'),
    add(make('p', ''), make('strong', '', 'What happened: '), found.what),
    add(make('p', ''), make('strong', '', 'What was kept: '), found.kept),
    add(make('div', 'bar'), go));
}

function questionPart(run, title) {
  const node = card('Needs you', 'card-needs');
  return add(node, questionBox(view.path, title, run.question, 'filled', 'answer-run'));
}

function gatePart(training, waiting, said) {
  const sentence = training.sentence || sentenceOf(waiting.label);
  return callout('yours', sentence === said ? null : make('p', '', sentence),
    waiting.question ? make('p', sentence === said ? '' : 'quiet',
      asker(training.path) + waiting.question) : null);
}

function sentenceOf(label) {
  return String(label).charAt(0).toUpperCase() + String(label).slice(1)
    + ' is waiting for your review.';
}

// What a step has taken so far. It moves while the step is working, so it is written into
// the step that is already on the screen rather than drawing the list again.
function stepFacts(step) {
  const facts = [];
  if (step.kind === 'gate') facts.push('Your decision');
  if (step.attempts > 1) facts.push(count(step.attempts, 'try', 'tries'));
  if (given(step.seconds)) facts.push(lasted(step.seconds));
  if (given(step.dollars)) facts.push(money(step.dollars));
  return facts.join(' · ');
}

function stepItem(step) {
  const [shape, words] = STEP_WORDS[step.status] || STEP_WORDS['to-do'];
  const facts = make('p', 'quiet step-facts', stepFacts(step));
  facts.hidden = !facts.textContent;
  const text = add(make('div', 'row-text'), make('p', 'step-name', step.label), facts);
  if (step.error) add(text, make('p', step.status === 'failed' ? 'problem' : 'quiet', step.error));
  const item = make('li', 'row step' + (step.status === 'working' ? ' working' : ''));
  item.dataset.state = step.status;
  return add(item, bead(shape), text, make('span', 'step-words', words));
}

function stepsCard(run) {
  const node = card('Steps');
  const steps = list(run.steps);
  if (!steps.length) return add(node, make('p', 'quiet', 'It is working out what to do first.'));
  const items = make('ol', 'rows');
  for (const step of steps) items.append(stepItem(step));
  return add(node, items);
}

function tickSteps(run) {
  const shown = main().querySelectorAll('.step-facts');
  list(run.steps).forEach((step, index) => {
    const said = stepFacts(step);
    if (!shown[index] || shown[index].textContent === said) return;
    shown[index].textContent = said;
    shown[index].hidden = !said;
  });
}

function workerItem(worker) {
  const lines = list(worker.lines);
  const item = add(make('li', 'worker'), add(make('div', 'computer-top'),
    make('h3', 'row-title', worker.label),
    add(make('span', 'quiet'), 'Started ', when(worker.started_at))));
  if (!lines.length) return add(item, make('p', 'quiet', 'Just starting.'));
  add(item, make('p', 'worker-now', lines[lines.length - 1]));
  if (lines.length > 1) {
    const before = make('details', 'worker-before');
    before.dataset.key = 'worker ' + worker.id;
    add(item, add(before, make('summary', '', 'What it did just before'),
      bullets(lines.slice(0, -1).reverse(), 'reasons')));
  }
  return item;
}

function workersCard(run) {
  const items = make('ul', 'plain workers');
  for (const worker of list(run.workers)) items.append(workerItem(worker));
  return add(card('Working now'), items);
}

function madeCard(training) {
  const node = card('Made so far');
  const made = list(training.view && training.view.files).filter((file) => !['not-started',
    'skipped', 'unavailable'].includes(file.status));
  if (!made.length) {
    add(node, make('p', 'quiet', 'Nothing yet. Each thing it makes appears here, ready to '
      + 'open.'));
  } else {
    const items = make('ul', 'rows');
    for (const file of made) {
      const words = file.waiting ? 'waiting for your review'
        : file.asked ? file.words + ', changes asked for' : file.words;
      const go = capsule(file.waiting ? 'Review' : 'Open', 'quiet',
        () => show('gate', { path: training.path, artifact: file.artifact }),
        'file ' + file.artifact);
      go.setAttribute('aria-label', (file.waiting ? 'Review ' : 'Open ') + lower(file.label));
      add(items, add(make('li', 'row'), bead(file.waiting ? 'review' : FILE_BEADS[file.status]),
        add(make('div', 'row-text'), make('p', 'step-name', file.label),
          make('p', 'quiet', words.charAt(0).toUpperCase() + words.slice(1))), go));
    }
    add(node, items);
  }
  return add(node, add(make('div', 'bar'), capsule('Everything about this training', 'quiet',
    () => show('training', { path: view.path }), 'detail')));
}

function costCard(run) {
  const node = card('What it has cost');
  const spent = run.spent || {};
  const limits = (view.setup && view.setup.limits) || {};
  const agent = AGENT_NAMES[run.agent] || run.agent || 'an agent';
  add(node, make('p', 'cost', given(spent.dollars) ? money(spent.dollars) : 'Not reported'));
  const says = [];
  const silent = !given(spent.dollars) && given(spent.tokens);
  if (given(spent.dollars)) says.push('So far.');
  else if (silent) says.push(agent + ' says how many tokens it uses, not what they cost.');
  else says.push('Nothing has been reported yet. An agent says what it used as each step ends.');
  if (given(spent.tokens)) says.push(Number(spent.tokens).toLocaleString() + ' tokens used.');
  if (given(limits.training_dollars)) {
    says.push(silent ? 'So the limit of ' + money(limits.training_dollars)
      + ' cannot stop it: watch the steps instead.'
      : 'It stops and asks you at ' + money(limits.training_dollars) + '.');
  }
  return add(node, make('p', 'quiet', says.join(' ')),
    make('p', 'quiet', 'Drafted by ' + agent + (run.model ? ', with the model ' + run.model
      : '') + '.'));
}

// --- a run: your own documents ---------------------------------------------------------
// With documents of your own, a run waits for them before it researches anything. They are
// sent one at a time, and each is refused here first if the runner would refuse it anyway.

// The ending of a file's name, as the runner names a type: lower case, with its dot.
function ending(name) {
  const at = String(name).lastIndexOf('.');
  return at < 0 ? '' : String(name).slice(at).toLowerCase();
}

function typesOf(held) {
  return list(held.types).map((type) => '.' + String(type).toLowerCase().replace(/^\./, ''));
}

// Why a file cannot be added, or nothing when it can. `room` is how many more may be.
function unfit(file, held, room) {
  const types = typesOf(held);
  const limits = held.limits || {};
  if (types.length && !types.includes(ending(file.name))) {
    return file.name + ' was not added: only ' + series(types) + ' files are taken.';
  }
  if (given(limits.bytes) && file.size > limits.bytes) {
    return file.name + ' was not added: it is ' + megabytes(file.size) + ', and a document '
      + 'can be at most ' + megabytes(limits.bytes) + '.';
  }
  if (room < 1) {
    return file.name + ' was not added: there is room for ' + limits.files
      + ' documents and no more.';
  }
  return '';
}

// A file as the runner takes it, in base64. The browser reads it, and puts a few words about
// its kind in front, up to a comma, which are left off.
function base64Of(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const read = String(reader.result);
      const at = read.indexOf(',');
      resolve(at < 0 ? '' : read.slice(at + 1));
    };
    reader.onerror = () => reject(new Error('This browser could not read it.'));
    reader.readAsDataURL(file);
  });
}

// While documents are being sent or removed, the card's controls wait.
function holdDocuments(held) {
  for (const node of main().querySelectorAll('.documents button, .documents input')) {
    node.disabled = held;
  }
}

// What was not added, said beside the control. The card may have been drawn again since.
function unadded(text) {
  view.unadded = text;
  const problem = byId('documents-file-problem');
  if (problem && problem.textContent !== text) refuse('documents-file', text);
}

function undone(text) {
  view.undone = text;
  if (byId('documents-problem')) say(byId('documents-problem'), text);
}

async function addDocuments(input) {
  const held = view.run.documents;
  const chosen = Array.from(input.files || []);
  if (view.busy || !chosen.length) return;
  const turn = view.turn;
  const limits = held.limits || {};
  let room = given(limits.files) ? limits.files - list(held.added).length : chosen.length;
  const refused = [];
  const taken = [];
  for (const file of chosen) {
    const why = unfit(file, held, room);
    if (why) {
      refused.push(why);
    } else {
      taken.push(file);
      room -= 1;
    }
  }
  // What was said about the files chosen last time is no longer about these.
  undone('');
  unadded('');
  if (!taken.length) {
    // Refused here, beside the control, before anything is sent.
    input.value = '';
    unadded(refused.join(' ') + ' Nothing was sent.');
    input.focus();
    return;
  }
  view.busy = true;
  holdDocuments(true);
  let added = 0;
  for (const [index, file] of taken.entries()) {
    say(byId('documents-status'), 'Adding ' + (index + 1) + ' of ' + taken.length + ': '
      + file.name);
    try {
      const content = await base64Of(file);
      view.run = await send('documents', { path: view.path, action: 'add', name: file.name,
        content });
      added += 1;
    } catch (failure) {
      refused.push(file.name + ' was not added. ' + failure.message);
      // With no answer at all, there is nobody to send the rest to.
      if (failure.kind === 'stopped') break;
    }
    if (turn !== view.turn) break;
  }
  view.busy = false;
  if (turn !== view.turn) return;
  input.value = '';
  holdDocuments(false);
  say(byId('documents-status'), '');
  paintRun(false);
  unadded(refused.join(' '));
  if (added) toast(count(added, 'document', 'documents') + ' added.');
  if (!focusKey('documents-file')) byId('title').focus({ preventScroll: true });
}

// Take one document away, or say that is all of them. The runner answers with the run.
async function settleDocuments(action, name, pressed) {
  if (view.busy) return;
  const turn = view.turn;
  view.busy = true;
  holdDocuments(true);
  let run;
  try {
    run = await send('documents', name ? { path: view.path, action, name }
      : { path: view.path, action });
  } catch (failure) {
    view.busy = false;
    if (turn !== view.turn) return;
    holdDocuments(false);
    undone(failure.message + ' Nothing was changed, and your documents are still here.');
    pressed.focus();
    return;
  }
  view.busy = false;
  if (turn !== view.turn) return;
  view.run = run;
  view.unadded = '';
  view.undone = '';
  toast(name ? name + ' is removed.' : 'That is all of them. It carries on from here.');
  paintRun(false);
  // A card that the answer left as it was is not drawn again, so its controls are let go here.
  holdDocuments(false);
  if (name) {
    if (!focusKey('documents-file')) byId('title').focus({ preventScroll: true });
    return;
  }
  // The card to add them is gone from the screen: show the run from the top, as it now stands.
  window.scrollTo(0, 0);
  byId('title').focus({ preventScroll: true });
  refresh();
}

function documentItem(found, waiting) {
  const text = add(make('div', 'row-text'), make('p', 'step-name', found.name),
    make('p', 'quiet', size(Number(found.bytes) || 0)));
  if (!found.readable) {
    add(text, make('p', 'problem', 'It could not be read' + (found.problem ? ': '
      + found.problem : '.')), make('p', 'quiet', 'It is kept, and is not used for the '
      + 'research.' + (waiting ? ' Remove it, or carry on without it.' : '')));
  }
  const item = make('li', 'row step');
  item.dataset.state = found.readable ? 'read' : 'unread';
  add(item, bead(found.readable ? 'done' : 'late'), text,
    make('span', 'step-words', found.readable ? 'Can be read' : 'Cannot be read'));
  if (!waiting) return item;
  const remove = capsule('Remove', 'quiet',
    () => settleDocuments('remove', found.name, remove), 'remove ' + found.name);
  remove.setAttribute('aria-label', 'Remove ' + found.name);
  return add(item, remove);
}

function documentsCard(run, lead) {
  const held = run.documents;
  const added = list(held.added);
  const limits = held.limits || {};
  const node = card(held.waiting ? 'Add your documents' : 'Your documents',
    'documents' + (held.waiting ? ' card-needs' : ''));
  if (held.waiting) {
    const types = typesOf(held);
    const takes = [types.length ? 'It takes ' + series(types) + ' files' : 'It takes files',
      given(limits.bytes) ? ', each up to ' + megabytes(limits.bytes) : '',
      given(limits.files) ? ', and ' + limits.files + ' in all' : ''].join('');
    const status = make('p', 'quiet');
    status.id = 'documents-status';
    status.setAttribute('role', 'status');
    status.hidden = true;
    add(node, make('p', '', 'Nothing is researched until you have added them and chosen '
      + '“That is all of them”.'), make('p', '', KEPT_HERE),
    field('documents-file', 'Add documents', {}, '', { picked: addDocuments,
      accept: types.join(','), refused: view.unadded,
      hint: takes + '. You can choose several at once.' }), status);
  } else {
    add(node, make('p', '', added.length ? 'These were given to the research. ' + KEPT_HERE
      : 'None were added.'));
  }
  if (held.note) add(node, make('p', 'quiet', held.note));
  if (added.length) {
    const items = make('ul', 'rows');
    for (const found of added) items.append(documentItem(found, held.waiting));
    add(node, make('h3', 'row-title', count(added.length, 'document', 'documents')
      + ' added'), items);
  } else if (held.waiting) {
    add(node, make('p', 'quiet', 'Nothing is added yet.'));
  }
  if (!held.waiting) return node;
  const problem = alertLine('documents-problem');
  say(problem, view.undone);
  const done = capsule('That is all of them', lead ? 'filled' : '',
    () => settleDocuments('done', '', done), 'documents-done');
  return add(node, problem, add(make('div', 'bar'), done));
}

// --- a run: the copies, the deck, and the end -------------------------------------------

// Where a copy is. A web address is a link to follow; anything else is a file in the
// training's folder, and is shown as where it is.
function copyLink(found, kind, what) {
  if (!found.link) return null;
  if (!WEB_LINK.test(found.link)) {
    return add(make('p', 'quiet'), 'Kept with the training as ',
      pathInto(make('span', 'path'), found.link));
  }
  const node = make('a', 'link', 'Open the ' + kind);
  node.href = found.link;
  node.rel = 'noopener noreferrer';
  node.target = '_blank';
  node.setAttribute('aria-label', 'Open the ' + what + ', in a new tab');
  return add(make('p', ''), node);
}

function copyItem(found) {
  const [shape, words] = COPY_STATES[found.state] || COPY_STATES['not-made'];
  const kind = COPY_KINDS[found.kind] || 'copy';
  const what = kind + ' of ' + lower(found.label);
  const text = add(make('div', 'row-text'),
    make('p', 'step-name', what.charAt(0).toUpperCase() + what.slice(1)));
  if (found.state === 'out-of-date') {
    add(text, make('p', '', 'Its file has changed since this copy was made.'));
  }
  const why = found.problem || (found.state === 'not-made' ? 'No reason was given.' : '');
  if (found.state !== 'made' && why) add(text, make('p', '', why));
  add(text, copyLink(found, kind, what));
  const item = make('li', 'row step');
  item.dataset.state = found.state;
  return add(item, bead(shape), text, make('span', 'step-words', words));
}

async function tryCopies() {
  if (view.copying) return;
  const turn = view.turn;
  view.copying = true;
  view.uncopied = '';
  paintRun(false);
  let run = null;
  let refusal = '';
  try {
    run = await send('copies', { path: view.path });
  } catch (failure) {
    refusal = failure.message + ' Nothing was changed: the copies are as they were.';
  }
  // Another screen is open by now, and it has put this one's state away.
  if (turn !== view.turn) return;
  view.copying = false;
  view.uncopied = refusal;
  if (run) {
    view.run = run;
    const left = list(run.copies).filter((found) => found.state !== 'made').length;
    toast(left ? count(left, 'copy is', 'copies are') + ' still not made. Each says why.'
      : 'Every copy is made.');
  }
  paintRun(false);
  if (!focusKey('copies-again')) byId('title').focus({ preventScroll: true });
}

function copiesCard(run) {
  const node = card('Copies');
  const items = make('ul', 'rows');
  for (const found of list(run.copies)) items.append(copyItem(found));
  add(node, items);
  if (!list(run.copies).some((found) => found.state !== 'made')) return node;
  const go = capsule(view.copying ? 'Trying again…' : 'Try the copies again', '', tryCopies,
    'copies-again');
  if (view.copying) go.setAttribute('aria-busy', 'true');
  const problem = alertLine('copies-problem');
  say(problem, view.uncopied);
  return add(node, make('p', 'quiet', 'The training itself is complete without them. A copy '
    + 'that is not made is listed as a limitation.'), problem, add(make('div', 'bar'), go));
}

// A deck this computer cannot make is the one stage a run leaves. It says what is missing in
// its own words, and leaving the deck out is the decision a gate has, with its reason.
function deckLeftPart(run) {
  const found = run.deck_left;
  const leave = capsule('Leave the deck out', '', () => {
    view.deciding = found.artifact;
    openSheet('skip', 'leave-deck')();
    paintRun(false);
  }, 'leave-deck');
  return callout('yours', make('h2', 'aside-title', 'What to do about the slide deck'),
    found.says === run.sentence ? null : make('p', '', found.says),
    make('p', 'quiet', 'Leaving it out takes a reason, which is kept with the training. You '
      + 'can bring the deck back later.'),
    add(make('div', 'bar'), leave));
}

function finishedPart(run, lead) {
  const found = run.finished;
  const limits = list(found.limitations);
  // The index is one more file of the training, read on a screen of its own.
  const open = found.index ? capsule('Open the index', lead && found.ready ? 'filled' : '',
    () => show('index', { path: view.path, artifact: found.index }), 'index') : null;
  const limited = limits.length ? [make('p', '', count(limits.length, 'thing was',
    'things were') + ' left out or limited:'), bullets(limits, 'reasons')] : [];
  const indexed = open ? make('p', 'quiet', 'The index lists every file, what was checked, '
    + 'and how to use the practice scenarios.') : null;
  if (found.ready) {
    return callout('', make('h2', 'aside-title', 'Ready to use'),
      ...(limited.length ? limited : [make('p', '', 'Nothing was left out or limited.')]),
      indexed, add(make('div', 'bar'), open));
  }
  const blocking = list(found.blocking);
  const go = capsule('See what is in the way', lead ? 'filled' : '',
    () => show('training', { path: view.path }), 'blocking');
  return callout('late', make('h2', 'aside-title', 'Not ready to use yet'),
    make('p', '', blocking.length ? count(blocking.length, 'thing is', 'things are')
      + ' in the way:' : 'Something is in the way, and it was not said what.'),
    blocking.length ? bullets(blocking, 'reasons') : null,
    add(make('p', ''), make('strong', '', 'What was kept: '), 'everything that was made.'),
    ...limited, indexed, add(make('div', 'bar'), go, open));
}

async function steer(action, pressed) {
  if (view.busy) return;
  const turn = view.turn;
  const key = pressed.dataset.key;
  view.busy = true;
  pressed.disabled = true;
  try {
    const run = await send('run', { path: view.path, action });
    view.busy = false;
    if (turn !== view.turn) return;
    view.run = run;
    view.steered = '';
    toast(STEERED[action]);
  } catch (failure) {
    view.busy = false;
    if (turn !== view.turn) return;
    view.steered = failure.message + ' Nothing was changed.';
  }
  view.barred = '';
  paintRun(false);
  // The control that was pressed may be gone. Focus goes to the one that undoes it, or to
  // the head of the screen, never to nowhere.
  const undo = { pause: 'resume', resume: 'pause', stop: 'resume' }[action];
  if (!focusKey(key) && !(undo && focusKey(undo))) byId('title').focus({ preventScroll: true });
  refresh();
}

// The toolbar's side of a run: pause, resume and stop, and one filled button for whatever
// is needed first.
function runActions(run, waiting, lead) {
  const actions = [];
  const press = (label, kind, action) => {
    const node = capsule(label, kind, () => steer(action, node), action);
    actions.push(node);
  };
  const offered = run.problem && run.problem.action;
  if (run.state === 'working') press('Pause', '', 'pause');
  if (['working', 'waiting', 'paused'].includes(run.state)) press('Stop', 'quiet', 'stop');
  if (['paused', 'stopped'].includes(run.state) && offered !== 'resume') {
    press('Resume', lead === 'resume' ? 'filled' : '', 'resume');
  }
  // A run that failed and says nothing more is still not a dead end.
  if (lead === 'retry') press('Try again', 'filled', 'retry');
  if (waiting && !run.question) {
    actions.push(capsule('Review ' + waiting.label, lead === 'review' ? 'filled' : '',
      () => show('gate', { path: view.path, artifact: waiting.artifact }), 'lead'));
  }
  // What a deck says is reviewed on a screen of its own, reached like any gate.
  if (outlining(run) && !run.question) {
    actions.push(capsule('Review ' + outlineLabel(run.outline),
      lead === 'outline' ? 'filled' : '', () => show('outline', { path: view.path }),
      'lead-outline'));
  }
  return actions;
}

// --- a run: the slide deck -----------------------------------------------------------------

function outlineLabel(outline) {
  return outline && outline.level ? 'what the level ' + outline.level + ' deck says'
    : 'what the deck says';
}

// What a deck says is waiting for its person. The run leads to it, and says why it matters.
function outlinePart(run) {
  const says = capital(outlineLabel(run.outline)) + ' is waiting for your review.';
  return callout('yours', says === run.sentence ? null : make('p', '', says),
    make('p', 'quiet', 'It is every slide’s words, before any slide is drawn. Words are '
      + 'quick to change now, and slow to change once the slides are drawn.'));
}

// What a deck of this size has cost before, so that this one is no surprise.
function costBefore(before) {
  const parts = [];
  if (given(before.dollars)) parts.push('about ' + money(before.dollars));
  if (given(before.minutes)) {
    parts.push('about ' + lasted(Number(before.minutes) * 60) + ' of agent time');
  }
  return parts.length ? 'A deck of this size has cost ' + parts.join(' and ') + ' before. '
    + 'It spends from the same limit as the rest of the training.' : '';
}

// One section of a deck while it is drawn: where it stands, how many previews it has used,
// and its slides as they were last previewed.
function sectionItem(section, index, titles) {
  const [shape, words] = SECTION_WORDS[section.state]
    || ['current', spoken(section.state || 'being drawn')];
  const slides = list(section.slides);
  const used = Number(section.previews) || 0;
  const text = add(make('div', 'row-text'), make('p', 'step-name', 'Section ' + (index + 1)),
    make('p', 'quiet', capital(slidesNamed(slides)) + ' · '
      + (used ? count(used, 'preview', 'previews') + ' used' : 'No preview yet')));
  if (used && slides.length) {
    const thumbs = make('ul', 'thumbs');
    for (const number of slides) {
      const name = make('span', 'thumb-name quiet', String(number));
      name.setAttribute('aria-hidden', 'true');
      // A new preview is a new picture of the same slide, so it is fetched again.
      add(thumbs, add(make('li', 'thumb'), pictureAt({ section: section.id, number },
        'Slide ' + number + (titles[number] ? ': ' + titles[number] : ''), used), name));
    }
    add(text, make('p', 'quiet', 'As last previewed:'), thumbs);
  }
  const item = make('li', 'row step section');
  item.dataset.state = section.state;
  return add(item, bead(shape), text, make('span', 'step-words', words));
}

function deckCard(run) {
  const deck = run.deck;
  const sections = list(deck.sections);
  const node = card(deck.level ? 'The level ' + deck.level + ' slide deck' : 'The slide deck',
    'deck');
  const cost = deck.before ? costBefore(deck.before) : '';
  if (cost) add(node, make('p', '', cost));
  if (!sections.length) {
    add(node, make('p', 'quiet', 'Its sections appear here once the deck is split into '
      + 'them.'));
  } else {
    // A slide is named by its title where what the deck says is still at hand to read it from.
    const titles = {};
    const said = run.outline && (run.outline.level || null) === (deck.level || null)
      ? list(run.outline.slides) : [];
    said.forEach((slide, index) => {
      titles[index + 1] = slide.title;
    });
    const items = make('ol', 'rows');
    sections.forEach((section, index) => items.append(sectionItem(section, index, titles)));
    add(node, make('p', '', 'It is drawn in sections, side by side. Each one draws its '
      + 'slides, looks at a preview of them, and puts right what it sees before handing in.'),
    items);
  }
  return add(node, run.outline ? add(make('div', 'bar'), capsule('Read '
    + outlineLabel(run.outline), 'quiet', () => show('outline', { path: view.path }),
  'read-outline')) : null);
}

function paintRun(fresh) {
  const run = view.run;
  const training = view.training
    || list(view.listing).find((found) => found.path === view.path) || {};
  const title = training.title || 'Untitled';
  const waiting = training.waiting && training.waiting.artifact ? training.waiting : null;
  const promised = view.promised && view.promised.path === view.path ? view.promised.gates : 0;
  const offered = run.problem && run.problem.action;
  const supplying = adding(run);
  const outline = outlining(run);
  // One filled button on the screen, for the first thing that is needed. While a sheet is
  // open it holds that button, so nothing under it is filled.
  const lead = view.sheet || view.after ? '' : run.question ? 'answer' : offered ? 'problem'
    : supplying ? 'documents' : waiting ? 'review' : outline ? 'outline'
      : run.finished ? 'finished' : ['paused', 'stopped'].includes(run.state) ? 'resume'
        : run.state === 'failed' && !run.problem ? 'retry' : '';
  const limits = (view.setup && view.setup.limits) || {};
  const above = [make('span', '', [levelsText(training.levels), 'Runs on this page']
    .filter(Boolean).join(' · '))];
  placeParts({ title, above, back: true, actions: runActions(run, waiting, lead),
    mark: [title, training.levels, run.state, lead, offered, waiting, outline
      && run.outline.level] }, [
    ['intro', [run.state, run.sentence, training.stages, promised, view.steered,
      nextGate(run), Boolean(run.problem), runStanding(run), supplying, outline],
    () => runIntro(run, training, promised)],
    run.problem ? ['problem', [run.problem, lead], () => problemPart(run, lead === 'problem')]
      : null,
    run.question ? ['question', [run.question, title], () => questionPart(run, title)] : null,
    supplying ? ['documents', [run.documents, lead],
      () => documentsCard(run, lead === 'documents')] : null,
    waiting && !run.question ? ['gate', [waiting, training.sentence],
      () => gatePart(training, waiting, run.sentence)] : null,
    outline && !run.question ? ['outline', [run.outline.level, run.sentence],
      () => outlinePart(run)] : null,
    run.deck_left ? ['deck-left', [run.deck_left, run.sentence], () => deckLeftPart(run)]
      : null,
    run.finished ? ['finished', [run.finished, lead],
      () => finishedPart(run, lead === 'finished')] : null,
    // While a deck is drawn, its sections and their latest previews are what there is to see.
    run.deck ? ['deck', [run.deck, run.outline && [run.outline.level,
      list(run.outline.slides).map((slide) => slide.title)]], () => deckCard(run)] : null,
    ['steps', list(run.steps).map((step) => [step.id, step.label, step.kind, step.status,
      step.attempts > 1, step.error]), () => stepsCard(run)],
    list(run.workers).length ? ['workers', run.workers, () => workersCard(run)] : null,
    ['made', [training.path, training.view && training.view.files], () => madeCard(training)],
    list(run.copies).length ? ['copies', [run.copies, view.copying, view.uncopied],
      () => copiesCard(run)] : null,
    // Once that is all of them, what was added is kept on the screen, with nothing to press.
    run.documents && !supplying ? ['documents', [run.documents, ''],
      () => documentsCard(run, false)] : null,
    ['cost', [run.spent, run.agent, run.model, limits.training_dollars], () => costCard(run)],
  ], fresh);
  tickSteps(run);
  tidyPictures();
}

async function drawRun(fresh) {
  const turn = view.turn;
  if (fresh) {
    place({ title: 'Opening', back: true }, [make('p', 'quiet', 'Reading the run.')], true);
  }
  try {
    const [run, training] = await Promise.all([ask('run', { path: view.path }),
      ask('training', { path: view.path }).catch(() => null)]);
    if (turn !== view.turn) return;
    const first = fresh || !view.run;
    view.run = run;
    if (training) view.training = training;
    // Someone is in the middle of leaving the deck out. The run waits until they are done.
    if (!view.busy && !view.sheet) paintRun(first);
    // A run just opened is read again at its own pace, not at the list's.
    if (first) later();
  } catch (failure) {
    if (turn !== view.turn) return;
    if (failure.kind === 'stopped') notify(failure.message);
    if (fresh || !view.run) {
      place({ title: 'This cannot be opened', back: true },
        [make('p', 'problem', failure.message),
          make('p', 'quiet', 'Nothing was changed. The training itself is as it was.'),
          capsule('Back to home', 'filled', () => show('home'), 'home')], fresh);
    }
  }
}

// --- what a deck says ------------------------------------------------------------------
// Every slide's words, put to the person before any slide is drawn. It is the runner's own
// gate, so it is read from the run and decided at an address of its own; it is drawn, and
// decided, like any other gate.

function outlined() {
  return Boolean(view.screen === 'outline' && view.run && view.run.outline);
}

// What there is to read here. When it changes under a reader, they say when to see it.
function outlineRead(outline) {
  return JSON.stringify([outline.level, outline.slides, outline.checked, outline.worth]);
}

// Everything this screen is drawn from. When none of it has changed, nothing is redrawn.
function outlineDrawn() {
  const training = list(view.listing).find((found) => found.path === view.path) || {};
  return JSON.stringify([view.run.outline, view.run.state, view.run.sentence,
    Boolean(view.newer), training.title, training.stages]);
}

// One slide, as something to read: what kind it is, what it says, what it is for, and its
// notes, which are there to open and not in the way.
function outlineSlide(slide, index) {
  const node = make('li', 'outline-slide');
  add(node, make('p', 'quiet outline-top', 'Slide ' + (index + 1) + ' · '
    + spoken(slide.kind || 'slide')),
  make('h3', 'outline-title', slide.title || 'No title'),
  slide.subtitle ? make('p', 'outline-subtitle', slide.subtitle) : null,
  slide.understand ? add(make('p', ''), make('strong', '', 'It should leave the audience '
    + 'understanding: '), slide.understand) : null);
  const points = list(slide.points);
  if (points.length) {
    const items = make('ul', 'outline-points');
    for (const point of points) {
      add(items, add(make('li'), point.label ? make('strong', '', point.label
        + (point.text ? ': ' : '')) : null, point.text || ''));
    }
    add(node, items);
  }
  const serves = list(slide.serves);
  add(node,
    slide.caveat ? add(make('p', ''), make('strong', '', 'Caveat: '), slide.caveat) : null,
    slide.source ? add(make('p', 'quiet'), make('strong', '', 'Source: '), slide.source) : null,
    serves.length ? make('p', 'quiet', 'Serves ' + (serves.length === 1 ? 'objective '
      : 'objectives ') + series(serves) + '.') : null);
  if (slide.notes) {
    const notes = make('details', 'outline-notes');
    notes.dataset.key = 'notes ' + (slide.id || index);
    add(node, add(notes, make('summary', '', 'Speaker notes for slide ' + (index + 1)),
      make('p', 'outline-said', slide.notes)));
  }
  return node;
}

function outlineChecked(outline) {
  const checked = list(outline.checked);
  return add(make('section', 'paper aside-part'), make('h2', 'aside-title', 'Checked for you'),
    checked.length ? bullets(checked, 'reasons') : make('p', 'quiet', 'No automatic checks '
      + 'apply here. It is yours to read.'));
}

function outlineWorth(outline) {
  const items = make('ul', 'look');
  for (const text of list(outline.worth)) add(items, add(make('li'), state('late', text)));
  if (outline.note) {
    add(items, add(make('li'), state('current', 'You asked for changes'),
      make('p', 'quote', outline.note)));
  }
  return add(make('section', 'paper aside-part'), make('h2', 'aside-title', 'Worth a look'),
    items.childNodes.length ? items : make('p', 'quiet', 'Nothing was flagged.'));
}

// What the screen says before anything is decided: a newer version, or nothing to decide.
function outlineStanding(run) {
  if (view.newer) {
    return callout('late', make('p', 'problem', 'This changed while you had it open.'),
      add(make('div', 'bar'), capsule('Show the new version', 'filled', () => {
        view.run = view.newer;
        view.newer = null;
        paintOutline(false);
      }, 'newer')));
  }
  if (run.outline.waiting) return null;
  return callout('', make('p', '', 'Nothing here is waiting for your decision now.'),
    make('p', 'quiet', run.sentence));
}

function paintOutline(fresh) {
  const run = view.run;
  const outline = run.outline;
  const training = list(view.listing).find((found) => found.path === view.path) || {};
  const title = training.title || 'Untitled';
  const label = capital(outlineLabel(outline));
  const home = () => show('run', { path: view.path });
  const above = [button(title, 'link', home, 'training'),
    outline && outline.level ? make('span', '', ' · Level ' + outline.level) : null];
  view.drawn = outlineDrawn();
  if (!outline) {
    // Reached before anything is written, or after it was put away: never a dead end.
    place({ title: label, name: label + ' · ' + title, above, back: true },
      [callout('', make('p', '', 'There is nothing here to read yet. What the deck says '
        + 'appears here once it is written.'), make('p', 'quiet', run.sentence)),
      add(make('div', 'bar'), capsule('Back to the run', view.after ? '' : 'filled', home,
        'home'))], fresh);
    drawSheet();
    return;
  }
  const slides = list(outline.slides);
  const items = make('ol', 'outline');
  slides.forEach((slide, index) => items.append(outlineSlide(slide, index)));
  const doc = add(make('article', 'paper doc'), make('h2', 'doc-title',
    count(slides.length, 'slide', 'slides') + ', in order'), items);
  doc.setAttribute('aria-label', label);
  const aside = add(make('aside', 'aside'), outlineChecked(outline), outlineWorth(outline));
  aside.setAttribute('aria-label', 'The review');
  const intro = add(make('div', 'intro'),
    state(...(outline.waiting ? ['review', 'Waiting for your review'] : runStanding(run))),
    list(training.stages).length ? beads(training.stages, false) : null,
    make('p', 'lede', 'This is every slide’s words, in order, before any slide is drawn. '
      + (outline.waiting ? 'Approve it, or say what should change: words are quick to change '
        + 'now, and slow to change once the slides are drawn.'
        : 'The slides are drawn from these words.')));
  // One filled button for the main thing to do, as at any gate. A newer version comes first.
  const actions = outline.waiting && !view.newer ? [
    capsule('Ask for changes', '', openSheet('revise', 'revise'), 'revise'),
    capsule('Approve', 'filled', openSheet('approve', 'lead'), 'lead')] : [];
  place({ title: label, name: label + ' · ' + title, above, back: true, actions },
    [intro, outlineStanding(run), add(make('div', 'gate'), aside,
      add(make('div', 'reading'), doc))], fresh);
  drawSheet();
}

async function drawOutline(fresh) {
  const turn = view.turn;
  if (fresh) {
    place({ title: 'Opening', back: true }, [make('p', 'quiet', 'Reading what the deck says.')],
      true);
  }
  try {
    const run = await ask('run', { path: view.path });
    if (turn !== view.turn) return;
    const held = view.run && view.run.outline;
    if (fresh || !held) {
      view.run = run;
      view.newer = null;
      // Someone may be in the middle of deciding what was here a moment ago.
      if (fresh || !(view.sheet || view.after)) paintOutline(fresh);
      return;
    }
    // Never swap what is being read under a reader: they say when to see the new one.
    const moved = Boolean(run.outline) && outlineRead(run.outline) !== outlineRead(held);
    if (view.sheet || view.after || view.busy) {
      if (moved) view.newer = run;
      return;
    }
    view.newer = moved ? run : null;
    if (!moved) view.run = run;
    if (outlineDrawn() !== view.drawn) paintOutline(false);
  } catch (failure) {
    if (turn !== view.turn) return;
    if (failure.kind === 'stopped') notify(failure.message);
    if (fresh || !view.run) {
      place({ title: 'This cannot be opened', back: true },
        [make('p', 'problem', failure.message),
          make('p', 'quiet', 'Nothing was changed. The training itself is as it was.'),
          capsule('Back to home', 'filled', () => show('home'), 'home')], fresh);
    }
  }
}

// The next thing that needs the person, read from the list. A decision at a gate is told it
// by the server; a decision about what a deck says is answered with the run alone.
function nextNeed() {
  const found = pick('needs-you')[0];
  if (!found) return null;
  const asked = view.asks[found.path] || {};
  const artifact = (found.waiting || {}).artifact || null;
  return { path: found.path, title: found.title || 'Untitled', artifact,
    outline: !artifact && readsOutline(asked),
    sentence: asked.problem ? asked.problem.what : saysOf(found) };
}

async function decideOutline(decision, note, problem, pressed) {
  if (view.busy) return;
  if (view.newer) {
    // Nothing is decided about words that were not read. Refused here, before it is sent.
    say(problem, 'This changed while you had it open. Cancel, and read the new version '
      + 'first.');
    return;
  }
  const turn = view.turn;
  view.busy = true;
  pressed.disabled = true;
  let run;
  try {
    run = await send('outline', { path: view.path, level: view.run.outline.level || null,
      decision, note: note || null });
  } catch (failure) {
    say(problem, failure.message);
    pressed.disabled = false;
    view.busy = false;
    return;
  }
  view.busy = false;
  if (turn !== view.turn) return;
  view.run = run;
  view.newer = null;
  view.sheet = '';
  const halted = ['paused', 'stopped', 'failed'].includes(run.state);
  const said = OUTLINE_SAID[decision] + ' ' + (halted ? HALTED
    : run.sentence + (run.state === 'working' ? ' ' + CLOSE : ''));
  let next = null;
  try {
    took(await ask('trainings'));
    await readAsks();
    next = nextNeed();
  } catch (failure) {
    // With the list out of reach, what happens next is still said; the way on is home.
    next = null;
  }
  if (turn !== view.turn) return;
  view.after = { said, next };
  paintOutline(false);
  byId('sheet').focus();
  refresh();
}

// --- the index -----------------------------------------------------------------------
// README.md at the top of a finished training, read like any other of its files. It is
// written once, when the training finishes, so it is read once and not again.

async function drawIndex(fresh) {
  if (!fresh) return;
  const turn = view.turn;
  const path = view.path;
  const found = list(view.listing).find((training) => training.path === path) || {};
  const home = () => show(homeOf(path), { path });
  view.drawn = 'index';
  place({ title: 'Opening', back: true }, [make('p', 'quiet', 'Reading the index.')], true);
  try {
    const read = await ask('file', { path, artifact: view.artifact });
    if (turn !== view.turn) return;
    place({ title: 'The index', name: 'The index · ' + (found.title || 'Untitled'), back: true,
      above: [button(found.title || 'Untitled', 'link', home, 'training')] },
    [add(make('div', 'reading index'), documentBody(asDocument(read),
      { label: 'The index', path, files: true }))], true);
  } catch (failure) {
    if (turn !== view.turn) return;
    if (failure.kind === 'stopped') notify(failure.message);
    place({ title: 'The index cannot be opened', back: true },
      [make('p', 'problem', failure.message),
        make('p', 'quiet', 'Nothing was changed. The training and everything it made are as '
          + 'they were.'),
        capsule('Back to the training', 'filled', home, 'home')], true);
  }
}

// --- staying up to date --------------------------------------------------------------

function waitingKey(training) {
  const waiting = training.waiting || {};
  // What a run needs when it is not at a gate is in its own sentence: a question, a problem.
  return training.path + '\n' + (waiting.artifact || '') + '\n' + (waiting.question || '')
    + (training.run && !waiting.artifact ? '\n' + training.run.sentence : '');
}

// Tell the person, once, about each new thing that needs them.
function took(listing) {
  view.listing = list(listing.trainings);
  view.needs = Number(listing.needs) || 0;
  const waiting = view.listing.filter((training) => training.state === 'needs-you');
  const keys = waiting.map(waitingKey);
  for (const training of view.known ? waiting : []) {
    if (view.known.includes(waitingKey(training))) continue;
    const said = (training.title || 'Untitled') + ': ' + saysOf(training);
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

// Someone is in the middle of writing in a box: the list is left as it is until they are done.
function typing() {
  const active = document.activeElement;
  return Boolean(active && (active.tagName === 'TEXTAREA' || active.tagName === 'INPUT')
    && active.value && main().contains(active));
}

// A run that is working is read more often, while its own screen is open.
function pace() {
  if (document.hidden) return POLL_HIDDEN;
  return view.screen === 'run' && view.run && view.run.state === 'working' ? POLL_RUN
    : POLL_SHOWN;
}

function later() {
  window.clearTimeout(view.timer);
  view.timer = window.setTimeout(refresh, pace());
}

async function refresh() {
  window.clearTimeout(view.timer);
  try {
    if (view.runner === undefined) await discover();
    if (view.runner) view.setup = await ask('setup');
    took(await ask('trainings'));
    await readAsks();
    if (view.computer === undefined) view.computer = (await ask('computer')).computer;
    notify('');
    setTitle();
    for (const node of document.querySelectorAll('time')) {
      const then = Date.parse(node.dateTime);
      if (!Number.isNaN(then)) node.textContent = ago(then);
    }
    frame();
    if (unset() && view.screen !== 'setup') {
      show('setup', null, true);
    } else if (['gate', 'training', 'run', 'outline'].includes(view.screen)) {
      await draw(false);
    } else if (view.screen === 'setup' || view.screen === 'new' || view.screen === 'index') {
      // A form is drawn once and never again under the person filling it in. So is the
      // index, under the person reading it.
      if (!view.drawn) draw(true);
    } else if (!view.busy && !view.checking && !typing() && view.drawn !== signature()) {
      draw(!view.drawn);
    }
  } catch (failure) {
    // Reading the list needs nothing but the key, so a refusal here is about the link.
    notify(failure.kind === 'refused' ? NOTICES.refused : failure.message);
  }
  later();
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
  // The arrow keys turn the slides at a deck's gate, from the slides themselves or from the
  // head of the screen. They are left alone in a sheet, in a box, and with a modifier held,
  // which is how a browser goes back.
  document.addEventListener('keydown', (event) => {
    const by = { ArrowLeft: -1, ArrowRight: 1 }[event.key];
    if (!by || !view.viewer || !byId('sheet').hidden) return;
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    const active = document.activeElement;
    const slides = byId('slides');
    if (active && ![document.body, byId('title'), main()].includes(active)
        && !(slides && slides.contains(active))) return;
    view.viewer.move(by);
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
