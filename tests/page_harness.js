// Runs the page's own scripts without a browser, for tests/test_desk.py.
//
//   node page_harness.js markdown        reads markdown on standard input, prints the tree
//                                        markdown.js builds from it
//   node page_harness.js app FILE        runs app.js against the answers in FILE, follows its
//                                        steps, and prints what was on the page at each one
//
// A step is one of: {snapshot: name}, {click: the name of a control}, {fill: the label of a
// box, value: what is typed}, {type: text} for the note in the sheet, {poll: true} for the
// page's own refresh, {key: 'Escape'}, and {attach: the label of a file picker, files: what
// is chosen in it}. A box that is filled is left as a person leaves it, unless the step says
// {stay: true}: then they are still typing in it. A chosen file is {name, text} or {name,
// bytes}; {size} says how large it claims to be, for one too large to write out here.
//
// An answer may be a picture: {status: 200, picture: its bytes in base64}. The page keeps
// one in memory under an address it makes up, and each snapshot says which pictures are on
// the screen and which are still held; what was let go is listed beside the requests.
// Nothing is laid out here, so nothing scrolls into view by itself: {see: the words a
// picture's place begins with} says that it has. A plan with {unwatched: true} is a browser
// that cannot say when anything comes into view.
//
// The document here has no HTML parser at all. A script that tried to set innerHTML would
// throw, so anything that reaches the page as markup fails the test that runs this.
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const PAGE = path.join(__dirname, '..', 'skills', 'training-studio', 'scripts', 'desk');
const NATIVE = ['BUTTON', 'A', 'SUMMARY', 'INPUT', 'TEXTAREA', 'SELECT'];
const report = { errors: [], requests: [], notifications: [], strayListeners: [], paces: [],
  released: [] };
// The pictures the page holds in memory: the address it made up for each, and what it is of.
const kept = new Map();
const watchers = [];

// --- a document with no parser -------------------------------------------------------

class FakeNode {
  constructor() {
    this.childNodes = [];
    this.parentNode = null;
  }

  remove() {
    if (!this.parentNode) return;
    const held = this.parentNode.childNodes;
    held.splice(held.indexOf(this), 1);
    this.parentNode = null;
  }

  contains(node) {
    for (let at = node; at; at = at.parentNode) if (at === this) return true;
    return false;
  }

  get nextSibling() {
    if (!this.parentNode) return null;
    const held = this.parentNode.childNodes;
    return held[held.indexOf(this) + 1] || null;
  }
}

class FakeText extends FakeNode {
  constructor(text) {
    super();
    this.nodeType = 3;
    this.data = String(text);
  }

  get textContent() {
    return this.data;
  }
}

function refuseMarkup() {
  throw new Error('The page tried to write markup. It must only ever set text.');
}

class FakeElement extends FakeNode {
  constructor(tag) {
    super();
    this.nodeType = tag === '#fragment' ? 11 : 1;
    this.tagName = tag.toUpperCase();
    this.attributes = {};
    this.dataset = {};
    this.listeners = {};
    this.style = {};
    this.hidden = false;
    this.off = false;
    this.readOnly = false;
    this.open = false;
    this.value = '';
    const owner = this;
    this.classList = {
      add: (...names) => { owner.className = [...new Set([...owner.classes(), ...names])].join(' '); },
      remove: (...names) => {
        owner.className = owner.classes().filter((name) => !names.includes(name)).join(' ');
      },
      contains: (name) => owner.classes().includes(name),
    };
  }

  classes() {
    return (this.attributes.class || '').split(/\s+/).filter(Boolean);
  }

  get disabled() {
    return this.off;
  }

  // A control that is switched off while it has the focus loses it, as it does in a browser.
  set disabled(value) {
    this.off = Boolean(value);
    if (this.off && document.activeElement === this) document.activeElement = document.body;
  }

  get className() {
    return this.attributes.class || '';
  }

  set className(value) {
    this.attributes.class = String(value);
  }

  get id() {
    return this.attributes.id || '';
  }

  set id(value) {
    this.attributes.id = String(value);
  }

  set innerHTML(value) { refuseMarkup(); }

  set outerHTML(value) { refuseMarkup(); }

  insertAdjacentHTML() { refuseMarkup(); }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  getAttribute(name) {
    return name in this.attributes ? this.attributes[name] : null;
  }

  removeAttribute(name) {
    delete this.attributes[name];
  }

  append(...nodes) {
    for (const given of nodes) {
      const node = typeof given === 'string' ? new FakeText(given) : given;
      if (node.nodeType === 11) {
        this.append(...node.childNodes.slice());
        continue;
      }
      node.remove();
      node.parentNode = this;
      this.childNodes.push(node);
    }
  }

  prepend(node) {
    const held = this.childNodes.slice();
    this.replaceChildren(node, ...held);
  }

  get firstChild() {
    return this.childNodes[0] || null;
  }

  insertBefore(node, before) {
    if (!before) {
      this.append(node);
      return node;
    }
    node.remove();
    node.parentNode = this;
    this.childNodes.splice(this.childNodes.indexOf(before), 0, node);
    return node;
  }

  replaceChildren(...nodes) {
    for (const child of this.childNodes.slice()) child.remove();
    this.append(...nodes);
  }

  get children() {
    return this.childNodes.filter((node) => node.nodeType === 1);
  }

  get textContent() {
    return this.childNodes.map((node) => node.textContent).join('');
  }

  set textContent(value) {
    this.replaceChildren(new FakeText(value));
  }

  addEventListener(type, listener) {
    (this.listeners[type] = this.listeners[type] || []).push(listener);
    if (type === 'click' && this.nodeType === 1 && !NATIVE.includes(this.tagName)) {
      report.strayListeners.push(this.tagName);
    }
  }

  dispatch(type, event) {
    for (const listener of this.listeners[type] || []) listener(event);
  }

  // What a click, or Enter or Space on a native control, does. The control has the focus,
  // as it does for anyone who reached it with the keyboard.
  click() {
    if (this.disabled) return;
    document.activeElement = this;
    const event = { target: this, preventDefault() {} };
    this.dispatch('click', event);
    if (this.tagName === 'SUMMARY' && this.parentNode) this.parentNode.open = !this.parentNode.open;
    if (this.tagName === 'BUTTON' && this.type === 'submit') {
      for (let at = this.parentNode; at; at = at.parentNode) {
        if (at.tagName === 'FORM') at.dispatch('submit', event);
      }
    }
  }

  focus() {
    document.activeElement = this;
  }

  select() {}

  all() {
    const found = [];
    for (const child of this.children) found.push(child, ...child.all());
    return found;
  }

  querySelectorAll(selector) {
    return this.all().filter((node) => selector.split(',').some((one) => matches(node, one.trim())));
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }
}

// Selectors as the page uses them: tag, .class, #id, [attribute] and [attribute="value"],
// together or one inside another.
function matchesOne(node, simple) {
  const parts = simple.match(/^[a-z0-9]+|[.#][\w-]+|\[[^\]]+\]/gi) || [];
  return parts.every((part) => {
    if (part.startsWith('.')) return node.classes().includes(part.slice(1));
    if (part.startsWith('#')) return node.id === part.slice(1);
    if (part.startsWith('[')) {
      const [name, value] = part.slice(1, -1).split('=');
      const held = name.startsWith('data-')
        ? node.dataset[name.slice(5).replace(/-(\w)/g, (whole, letter) => letter.toUpperCase())]
        : name === 'open' ? (node.open ? '' : undefined) : node.attributes[name];
      if (held === undefined) return false;
      return value === undefined || held === value.replace(/^"|"$/g, '');
    }
    return node.tagName === part.toUpperCase();
  });
}

function matches(node, selector) {
  const chain = selector.replace(/\s*>\s*/g, ' ').split(/\s+/);
  if (!matchesOne(node, chain.pop())) return false;
  let at = node.parentNode;
  while (chain.length && at) {
    if (at.nodeType === 1 && matchesOne(at, chain[chain.length - 1])) chain.pop();
    at = at.parentNode;
  }
  return !chain.length;
}

const documentListeners = {};
const windowListeners = {};
const document = {
  body: new FakeElement('body'),
  activeElement: null,
  hidden: false,
  title: '',
  createElement: (tag) => new FakeElement(tag),
  createElementNS: (space, tag) => new FakeElement(tag),
  createTextNode: (text) => new FakeText(text),
  createDocumentFragment: () => new FakeElement('#fragment'),
  getElementById: (id) => document.body.all().find((node) => node.id === id) || null,
  querySelector: (selector) => document.body.querySelector(selector),
  querySelectorAll: (selector) => document.body.querySelectorAll(selector),
  addEventListener: (type, listener) => {
    (documentListeners[type] = documentListeners[type] || []).push(listener);
  },
  execCommand: () => false,
};

function tree(node) {
  if (node.nodeType === 3) return node.data;
  const shown = { tag: node.tagName.toLowerCase() };
  for (const name of ['href', 'rel', 'target', 'start', 'scope']) {
    if (node[name] !== undefined) shown[name] = node[name];
  }
  if (node.className) shown.class = node.className;
  if (node.childNodes.length) shown.children = node.childNodes.map(tree);
  return shown;
}

// --- markdown ----------------------------------------------------------------------

function markdown() {
  global.document = document;
  const renderer = require(path.join(PAGE, 'markdown.js'));
  const text = fs.readFileSync(0, 'utf8');
  // A third word, "files", draws it as a document that lists its training's own files.
  console.log(JSON.stringify(tree(renderer.render(text, { files: process.argv[3] === 'files' }))));
}

// --- the page itself ---------------------------------------------------------------

function settle() {
  return new Promise((resolve) => setImmediate(() => setImmediate(() => setImmediate(resolve))));
}

function visible(node) {
  for (let at = node; at; at = at.parentNode) {
    if (at.hidden || (at.tagName === 'DETAILS' && !at.open && node !== at
        && !at.children.filter((child) => child.tagName === 'SUMMARY').some((s) => s.contains(node)))) {
      return false;
    }
  }
  return true;
}

function name(node) {
  return (node.getAttribute('aria-label') || node.textContent || '').trim();
}

function words(node) {
  if (node.nodeType === 3) return node.data;
  if (node.hidden) return '';
  const inline = ['SPAN', 'CODE', 'STRONG', 'EM', 'A', 'BUTTON', 'P', 'LI', 'H1', 'H2', 'H3',
    'TIME', 'TH', 'TD', 'LABEL', 'SUMMARY'];
  return node.childNodes.map(words).join(inline.includes(node.tagName) ? '' : '\n');
}

// The boxes a person can type in, each under the words of its label.
function boxes() {
  const found = [];
  for (const label of document.body.querySelectorAll('label').filter(visible)) {
    const box = label.htmlFor ? document.getElementById(label.htmlFor) : null;
    if (box && visible(box)) found.push([name(label), box]);
  }
  return found;
}

function box(label) {
  const all = boxes();
  const exact = all.filter(([words]) => words === label);
  const found = exact.length ? exact : all.filter(([words]) => words.startsWith(label));
  if (!found.length) throw new Error('No box on the page is labelled "' + label + '".');
  return found[0][1];
}

// There are no object URLs here. The page is handed a made-up address for what it fetched,
// and letting go of one is remembered, so a test can see what is held and what was let go.
const objects = {
  made: 0,
  createObjectURL(fetched) {
    this.made += 1;
    kept.set('memory:' + this.made, fetched.from);
    return 'memory:' + this.made;
  },
  revokeObjectURL(address) {
    if (kept.has(address)) report.released.push(kept.get(address));
    kept.delete(address);
  },
};

// What says a picture's place has come into view. Here only a step says so.
class IntersectionObserver {
  constructor(seen) {
    this.seen = seen;
    this.watched = [];
    watchers.push(this);
  }

  observe(node) { this.watched.push(node); }

  unobserve(node) { this.watched = this.watched.filter((other) => other !== node); }

  disconnect() { this.watched = []; }
}

function see(words) {
  for (const watcher of watchers) {
    const found = watcher.watched.filter((node) => document.body.contains(node)
      && visible(node) && name(node).startsWith(words));
    if (found.length) watcher.seen(found.map((target) => ({ target, isIntersecting: true })));
  }
}

// A picture is the page's own when it is shown from memory. Any other is from somewhere else.
function own(node) {
  return node.tagName === 'IMG' && kept.has(node.src);
}

function snapshot() {
  const controls = document.body.querySelectorAll('button, a, summary, textarea, input');
  const unnamed = [];
  for (const control of controls) {
    if (control.tagName === 'TEXTAREA' || control.tagName === 'INPUT') {
      if (control.getAttribute('aria-hidden') === 'true') continue;
      const labelled = document.body.querySelectorAll('label')
        .some((label) => label.htmlFor && label.htmlFor === control.id && name(label));
      if (!labelled && !control.getAttribute('aria-label')) unnamed.push(control.tagName);
    } else if (!name(control)) {
      unnamed.push(control.tagName + '.' + control.className);
    }
  }
  const sheet = document.getElementById('sheet');
  const badge = document.getElementById('needs-count');
  return {
    title: document.title,
    heading: document.getElementById('title').textContent,
    text: words(document.body).replace(/\n+/g, '\n'),
    buttons: controls.filter((node) => node.tagName !== 'A' && visible(node)).map(name),
    filled: document.body.querySelectorAll('.button-filled').filter(visible).map(name),
    pressed: document.body.querySelectorAll('.seg-option').filter(visible)
      .filter((node) => node.getAttribute('aria-pressed') === 'true').map(name),
    beads: [...new Set(document.body.querySelectorAll('.bead').map((node) => node.dataset.state))],
    bareBeads: document.body.querySelectorAll('.bead')
      .filter((node) => !name(node.parentNode)).length,
    unnamed,
    foreign: document.body.querySelectorAll('img, script, iframe, object, embed')
      .filter((node) => !own(node)).length,
    pictures: document.body.querySelectorAll('img').filter((node) => own(node) && visible(node))
      .map((node) => ({ alt: node.alt || '', of: kept.get(node.src) })),
    held: [...kept.values()],
    focus: document.activeElement === document.body ? '(nowhere)'
      : document.activeElement ? (document.activeElement.id || name(document.activeElement)) : '',
    notice: document.getElementById('notice').hidden ? '' : document.getElementById('notice').textContent,
    current: document.body.querySelectorAll('[aria-current]').map(name),
    sheet: sheet.hidden ? '' : words(sheet).replace(/\n+/g, '\n'),
    toasts: document.body.querySelectorAll('.toast').map((node) => node.textContent),
    links: document.body.querySelectorAll('a').filter((node) => visible(node) && node.href)
      .map((node) => ({ name: name(node), href: node.href, rel: node.rel,
        target: node.target })),
    off: controls.filter((node) => visible(node) && node.disabled)
      .map((node) => name(node) || node.id),
    posts: report.requests.filter((request) => request.method === 'POST').length,
    badge: badge.hidden ? '' : badge.textContent,
    fields: Object.fromEntries(boxes().map(([label, held]) => [label, held.value])),
    locked: boxes().filter(([, held]) => held.readOnly).map(([label]) => label),
    invalid: boxes().filter(([, held]) => held.getAttribute('aria-invalid') === 'true')
      .map(([label]) => label),
    chosen: document.body.querySelectorAll('.chip').filter(visible)
      .filter((node) => node.getAttribute('aria-pressed') === 'true').map(name),
    working: document.body.querySelectorAll('.working').filter(visible).length,
    sidebar: !document.getElementById('sidebar').hidden,
    pace: report.paces[report.paces.length - 1] || 0,
  };
}

// There is no File API here. A chosen file is its name, its size and its bytes, and the one
// way the page reads a file is stood in for: the bytes, in base64, after a few words and a
// comma, handed over a moment later.
function chosen(file) {
  const bytes = Buffer.from(file.bytes || file.text || '');
  return { name: file.name, type: file.type || '', bytes,
    size: file.size === undefined ? bytes.length : file.size };
}

class FileReader {
  readAsDataURL(file) {
    queueMicrotask(() => {
      this.result = 'data:' + (file.type || 'application/octet-stream') + ';base64,'
        + file.bytes.toString('base64');
      if (this.onload) this.onload();
    });
  }
}

function control(label) {
  const all = document.body.querySelectorAll('button, summary, a').filter(visible);
  const exact = all.filter((node) => name(node) === label);
  const found = exact.length ? exact : all.filter((node) => name(node).startsWith(label));
  if (!found.length) throw new Error('Nothing on the page is named "' + label + '".');
  return found[0];
}

// The page's own shell, read from index.html. It is the one piece of markup there is, it is
// ours, and it is read here only to stand the document up: the scripts never parse any.
function build(shell) {
  const body = /<body>([\s\S]*)<\/body>/.exec(shell)[1];
  const open = [document.body];
  const token = /<!--[\s\S]*?-->|<\/(\w+)>|<(\w+)((?:\s+[\w-]+(?:="[^"]*")?)*)\s*>|([^<]+)/g;
  for (const [, closing, tag, attributes, text] of body.matchAll(token)) {
    const parent = open[open.length - 1];
    if (closing) {
      open.pop();
    } else if (tag) {
      const node = new FakeElement(tag);
      for (const [, key, value] of (attributes || '').matchAll(/([\w-]+)(?:="([^"]*)")?/g)) {
        if (key === 'hidden') node.hidden = true;
        else if (key === 'type') node.type = value;
        else node.setAttribute(key, value || '');
      }
      if (tag === 'noscript') node.hidden = true;
      parent.append(node);
      open.push(node);
    } else if (text && text.trim()) {
      parent.append(new FakeText(text.trim()));
    }
  }
}

async function app(file) {
  const plan = JSON.parse(fs.readFileSync(file, 'utf8'));
  const answers = plan.answers;
  const timers = [];
  build(fs.readFileSync(path.join(PAGE, 'index.html'), 'utf8'));

  class Notification {
    constructor(title, options) {
      report.notifications.push({ title, body: options && options.body });
    }

    static requestPermission() {
      Notification.permission = 'granted';
      return Promise.resolve('granted');
    }
  }
  Notification.permission = plan.notifications || 'default';

  const window = {
    document,
    Notification,
    location: { hash: plan.hash === undefined ? '#token=the-test-key' : plan.hash },
    history: {
      state: null,
      earlier: [],
      pushState(state) {
        this.earlier.push(this.state);
        this.state = state;
      },
      replaceState(state) { this.state = state; },
      // The browser's own way back: the state before this one, announced to the page.
      back() {
        if (!this.earlier.length) return;
        this.state = this.earlier.pop();
        for (const listener of windowListeners.popstate || []) listener({ state: this.state });
      },
    },
    navigator: { clipboard: { writeText: () => Promise.resolve() } },
    FileReader,
    addEventListener: (type, listener) => {
      (windowListeners[type] = windowListeners[type] || []).push(listener);
    },
    scrollTo() {},
    focus() {},
    matchMedia: () => ({ matches: false }),
    setTimeout: (callback, delay) => {
      if (callback.name === 'refresh') report.paces.push(delay);
      return timers.push(callback);
    },
    clearTimeout() {},
    URLSearchParams,
    URL: objects,
    ...(plan.unwatched ? {} : { IntersectionObserver }),
    console,
    fetch: async (address, options) => {
      const method = (options && options.method) || 'GET';
      const key = method + ' ' + address.split('?')[0];
      report.requests.push({ method, address, headers: (options && options.headers) || {},
        body: options && options.body ? JSON.parse(options.body) : null });
      // An answer can be kept for one address, query and all, or for every query of it.
      const held = answers[method + ' ' + address] || answers[key];
      if (!held) return { ok: false, status: 404, json: async () => ({ error: 'No answer for ' + key }) };
      const answer = held.length > 1 ? held.shift() : held[0];
      if (answer.picture === undefined) {
        return { ok: answer.status === 200, status: answer.status, json: async () => answer.body };
      }
      // A picture is answered as bytes: what the page is handed says what kind they are, how
      // many there are, and which request they answer.
      return { ok: true, status: 200, json: async () => { throw new Error('Not JSON.'); },
        blob: async () => ({ type: answer.type || 'image/png',
          size: Buffer.from(answer.picture, 'base64').length, from: address }) };
    },
  };
  window.window = window;
  window.navigator.clipboard.writeText = () => Promise.resolve();
  const context = vm.createContext(window);
  context.navigator = window.navigator;
  for (const script of ['markdown.js', 'app.js']) {
    vm.runInContext(fs.readFileSync(path.join(PAGE, script), 'utf8'), context, { filename: script });
  }
  await settle();
  const shots = {};
  for (const step of plan.steps) {
    try {
      if (step.snapshot) shots[step.snapshot] = snapshot();
      if (step.click) control(step.click).click();
      if (step.type !== undefined) document.getElementById('note-text').value = step.type;
      if (step.fill !== undefined) {
        const held = box(step.fill);
        held.focus();
        held.value = step.value;
        held.dispatch('input', { target: held });
        if (!step.stay) held.dispatch('change', { target: held });
      }
      if (step.attach !== undefined) {
        const held = box(step.attach);
        held.focus();
        held.files = step.files.map(chosen);
        held.dispatch('change', { target: held });
      }
      if (step.see !== undefined) see(step.see);
      if (step.poll) await timers.filter((timer) => timer.name === 'refresh').pop()();
      if (step.key) for (const listener of documentListeners.keydown || []) listener({ key: step.key });
    } catch (failure) {
      report.errors.push(String(failure && failure.stack ? failure.stack : failure));
    }
    await settle();
  }
  console.log(JSON.stringify({ ...report, snapshots: shots }));
}

process.on('unhandledRejection', (failure) => {
  report.errors.push('Unhandled: ' + String(failure && failure.stack ? failure.stack : failure));
});

const [mode, file] = process.argv.slice(2);
if (mode === 'markdown') markdown();
else app(file).catch((failure) => {
  console.log(JSON.stringify({ ...report, errors: [...report.errors, String(failure.stack)] }));
});
