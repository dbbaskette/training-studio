// A small markdown renderer for the page. It builds DOM nodes and sets their text; nothing a
// document says is ever parsed as markup. It covers what a training's files use: headings,
// paragraphs, lists, tables, block quotes, code, emphasis and links. HTML comments, such as
// the coverage comments in a guide, are left out. Any other markup is shown as the text it is.
'use strict';

(function () {
  const FENCE = /^ {0,3}(`{3,}|~{3,})(.*)$/;
  const HEADING = /^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$/;
  const RULE = /^ {0,3}([-*_])(?:\s*\1){2,}\s*$/;
  const ITEM = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/;
  const QUOTE = /^ {0,3}>\s?(.*)$/;
  const DIVIDER = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;
  const ESCAPED = /\\([\\`*_{}[\]()#+\-.!|<>~])/g;
  const SAFE_LINK = /^https?:\/\/[^\s]+$/i;
  // A file of the training's own, named from its folder: no scheme, no leading slash, no "..".
  const OWN_FILE = /^(?!\/)(?!.*\.\.)[A-Za-z0-9._@\/-]+$/;
  let ownFiles = false; // set while a document that names its training's files is drawn
  const HIDDEN = 0xe000; // escaped characters wait here, in the private-use range

  function element(tag, className) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    return node;
  }

  function hide(text) {
    return text.replace(ESCAPED, (whole, character) =>
      String.fromCharCode(HIDDEN + character.charCodeAt(0)));
  }

  // In running text an escaped character is shown without its backslash; in code, with it.
  function reveal(text, slash) {
    let shown = '';
    for (const character of text) {
      const code = character.charCodeAt(0);
      const held = code >= HIDDEN && code < HIDDEN + 128;
      shown += held ? slash + String.fromCharCode(code - HIDDEN) : character;
    }
    return shown;
  }

  function words(parent, text) {
    if (text) parent.append(document.createTextNode(reveal(text, '')));
  }

  // Leave out <!-- comments -->, which may run over several lines, except inside code.
  function withoutComments(source) {
    const kept = [];
    let fence = '';
    let inside = false;
    for (const original of source.split('\n')) {
      let line = original;
      const fenced = FENCE.exec(line);
      if (!inside && fenced && (!fence || line.trim().startsWith(fence))) {
        fence = fence ? '' : fenced[1];
        kept.push(line);
        continue;
      }
      if (fence) {
        kept.push(line);
        continue;
      }
      let rest = '';
      let removed = inside;
      while (line) {
        if (inside) {
          const end = line.indexOf('-->');
          if (end < 0) {
            line = '';
          } else {
            line = line.slice(end + 3);
            inside = false;
          }
        } else {
          const start = line.indexOf('<!--');
          if (start < 0) {
            rest += line;
            line = '';
          } else {
            rest += line.slice(0, start);
            line = line.slice(start + 4);
            inside = true;
            removed = true;
          }
        }
      }
      // A line that held only a comment leaves nothing behind, not an empty paragraph.
      if (removed && !rest.trim()) continue;
      kept.push(rest);
    }
    return kept;
  }

  // --- inline: code, links, strong, emphasis -------------------------------------

  const INLINE = [
    { kind: 'code', pattern: /(`+)([^`]|[^`][\s\S]*?[^`])\1(?!`)/g },
    { kind: 'link', pattern: /\[([^\]]+)\]\(\s*<?([^\s)>]+)>?(?:\s+"[^"]*")?\s*\)/g },
    { kind: 'address', pattern: /<(https?:\/\/[^\s>]+)>/gi },
    { kind: 'strong', pattern: /\*\*(?=\S)([\s\S]*?\S)\*\*/g },
    { kind: 'strong', pattern: /__(?=\S)([\s\S]*?\S)__/g, wordy: true },
    { kind: 'em', pattern: /\*(?=[^\s*])([^*]*?[^\s*])\*/g },
    { kind: 'em', pattern: /_(?=[^\s_])([^_]*?[^\s_])_/g, wordy: true },
  ];
  const WORD = /[A-Za-z0-9]/;

  function earliest(text) {
    let best = null;
    for (const rule of INLINE) {
      rule.pattern.lastIndex = 0;
      let found = rule.pattern.exec(text);
      // An underscore inside a word, as in a file name, is not emphasis.
      while (found && rule.wordy && (WORD.test(text[found.index - 1] || '')
          || WORD.test(text[found.index + found[0].length] || ''))) {
        rule.pattern.lastIndex = found.index + 1;
        found = rule.pattern.exec(text);
      }
      if (found && (!best || found.index < best.found.index)) best = { rule, found };
    }
    return best;
  }

  function link(parent, label, address) {
    const target = reveal(address, '');
    if (!SAFE_LINK.test(target)) {
      // Not a web address, so never a link. In a document that lists its training's own
      // files, a file is named plainly; anywhere else it is shown as it was written.
      if (ownFiles && label !== null && OWN_FILE.test(address)) {
        words(parent, label === address ? address : label + ' (' + address + ')');
      } else {
        words(parent, label === null ? address : '[' + label + '](' + address + ')');
      }
      return;
    }
    const node = element('a');
    node.href = target;
    node.rel = 'noopener noreferrer';
    node.target = '_blank';
    if (label === null) words(node, address);
    else inline(node, label);
    parent.append(node);
  }

  function inline(parent, text) {
    let rest = text;
    while (rest) {
      const next = earliest(rest);
      if (!next) break;
      const { rule, found } = next;
      words(parent, rest.slice(0, found.index));
      if (rule.kind === 'code') {
        const node = element('code');
        node.textContent = reveal(found[2], '\\').trim();
        parent.append(node);
      } else if (rule.kind === 'link') {
        link(parent, found[1], found[2]);
      } else if (rule.kind === 'address') {
        link(parent, null, found[1]);
      } else {
        const node = element(rule.kind);
        inline(node, found[1]);
        parent.append(node);
      }
      rest = rest.slice(found.index + found[0].length);
    }
    words(parent, rest);
  }

  // Lines of one paragraph keep their breaks: a training's files put one field on a line.
  function lines(parent, held) {
    held.forEach((line, index) => {
      if (index) parent.append(element('br'));
      inline(parent, line.trim());
    });
  }

  // --- blocks --------------------------------------------------------------------

  function cells(line) {
    let row = line.trim();
    if (row.startsWith('|')) row = row.slice(1);
    if (row.endsWith('|')) row = row.slice(0, -1);
    return row.split('|').map((cell) => cell.trim());
  }

  function table(head, rows) {
    const wrap = element('div', 'md-table');
    wrap.tabIndex = 0;
    const node = element('table');
    const top = element('tr');
    for (const cell of cells(head)) {
      const heading = element('th');
      heading.scope = 'col';
      inline(heading, cell);
      top.append(heading);
    }
    const header = element('thead');
    header.append(top);
    const body = element('tbody');
    for (const row of rows) {
      const line = element('tr');
      for (const cell of cells(row)) {
        const held = element('td');
        inline(held, cell);
        line.append(held);
      }
      body.append(line);
    }
    node.append(header, body);
    wrap.append(node);
    return wrap;
  }

  function list(held) {
    const fragment = document.createDocumentFragment();
    const open = []; // the lists being built, outermost first
    const items = [];
    let item = null;
    for (const line of held) {
      const found = ITEM.exec(line);
      if (!found) {
        if (item) item.text.push(line);
        continue;
      }
      const indent = found[1].length;
      while (open.length && indent < open[open.length - 1].indent) open.pop();
      let level = open[open.length - 1];
      if (!level || indent > level.indent) {
        const numbered = /^\d/.test(found[2]);
        const node = element(numbered ? 'ol' : 'ul');
        if (numbered && parseInt(found[2], 10) !== 1) node.start = parseInt(found[2], 10);
        if (level && level.item) level.item.nested.push(node);
        else fragment.append(node);
        level = { indent, node, item: null };
        open.push(level);
      }
      item = { node: element('li'), text: [found[3]], nested: [] };
      level.node.append(item.node);
      level.item = item;
      items.push(item);
    }
    for (const made of items) {
      lines(made.node, made.text);
      made.node.append(...made.nested);
    }
    return fragment;
  }

  function blocks(parent, source, depth) {
    let at = 0;
    let paragraph = [];
    const flush = () => {
      if (!paragraph.length) return;
      const node = element('p');
      lines(node, paragraph);
      parent.append(node);
      paragraph = [];
    };
    while (at < source.length) {
      const line = source[at];
      const fenced = FENCE.exec(line);
      if (fenced) {
        flush();
        const body = [];
        at += 1;
        while (at < source.length && !source[at].trim().startsWith(fenced[1])) {
          body.push(source[at]);
          at += 1;
        }
        at += 1;
        const node = element('pre');
        const code = element('code');
        code.textContent = body.join('\n');
        node.tabIndex = 0;
        node.append(code);
        parent.append(node);
        continue;
      }
      if (!line.trim()) {
        flush();
        at += 1;
        continue;
      }
      const heading = HEADING.exec(line);
      if (heading) {
        flush();
        // One level down: the page's own heading is the training's title.
        const node = element('h' + Math.min(6, heading[1].length + 1));
        inline(node, hide(heading[2]));
        parent.append(node);
        at += 1;
        continue;
      }
      if (RULE.test(line)) {
        flush();
        parent.append(element('hr'));
        at += 1;
        continue;
      }
      if (QUOTE.test(line) && depth < 4) {
        flush();
        const body = [];
        while (at < source.length && QUOTE.test(source[at])) {
          body.push(QUOTE.exec(source[at])[1]);
          at += 1;
        }
        const node = element('blockquote');
        blocks(node, body, depth + 1);
        parent.append(node);
        continue;
      }
      if (line.includes('|') && at + 1 < source.length && DIVIDER.test(source[at + 1])
          && source[at + 1].includes('-')) {
        flush();
        const rows = [];
        const head = hide(line);
        at += 2;
        while (at < source.length && source[at].trim() && source[at].includes('|')) {
          rows.push(hide(source[at]));
          at += 1;
        }
        parent.append(table(head, rows));
        continue;
      }
      if (ITEM.test(line)) {
        flush();
        const held = [];
        // An item's own text may run on, indented. Anything else ends the list.
        while (at < source.length && source[at].trim()
            && (ITEM.test(source[at]) || /^\s{2,}\S/.test(source[at]))) {
          held.push(hide(source[at]));
          at += 1;
        }
        parent.append(list(held));
        continue;
      }
      paragraph.push(hide(line));
      at += 1;
    }
    flush();
  }

  // The document as a tree of elements. `text` is never read as markup. `about.files` says
  // the document lists files of its own training, as an index does.
  function render(text, about) {
    const node = element('div', 'md');
    ownFiles = Boolean(about && about.files);
    try {
      blocks(node, withoutComments(String(text).replace(/\r\n?/g, '\n')), 0);
    } finally {
      ownFiles = false;
    }
    return node;
  }

  const api = { render };
  if (typeof window !== 'undefined') window.TrainingStudioMarkdown = api;
  if (typeof module !== 'undefined') module.exports = api;
})();
