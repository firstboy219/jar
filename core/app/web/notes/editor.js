// The block editor of Catatan (ADR-060), Notion-style: one editable element per block, "/" for the block menu, Markdown shortcuts
// ("# ", "- ", "[] ", "> ", "```"), Enter / Backspace / Tab the way a writer expects, drag a block by its handle, and a small toolbar
// over the phone's keyboard. Plain text only: what is stored is what is seen.
import { BLOCK_TYPES, LIST_TYPES, PRIORITY, dueLabel, isoDay, filterSlash, hiddenByToggles, nextPriority, numberOf, parseLines, shortcutFor } from './lib.js';

const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const uid = () => Math.random().toString(36).slice(2, 11);
const PLAIN = (() => { const d = document.createElement('div'); d.contentEditable = 'plaintext-only'; return d.contentEditable === 'plaintext-only'; })();

function caret(node) {
  const s = getSelection();
  if (!s.rangeCount || !node.contains(s.anchorNode)) return { start: 0, end: 0 };
  const r = s.getRangeAt(0), pre = r.cloneRange();
  pre.selectNodeContents(node); pre.setEnd(r.startContainer, r.startOffset);
  const start = pre.toString().length;
  return { start, end: start + r.toString().length };
}
function placeCaret(node, offset) {
  node.focus({ preventScroll: false });
  const s = getSelection(), r = document.createRange();
  let left = Math.max(0, Math.min(offset, node.textContent.length)), done = false;
  const walk = (n) => {
    if (done) return;
    if (n.nodeType === 3) {
      if (left <= n.length) { r.setStart(n, left); done = true; return; }
      left -= n.length;
    } else for (const c of n.childNodes) walk(c);
  };
  walk(node);
  if (!done) { r.selectNodeContents(node); r.collapse(false); }
  r.collapse(true); s.removeAllRanges(); s.addRange(r);
}
const onFirstLine = (node) => { const { start } = caret(node); return !node.textContent.slice(0, start).includes('\n'); };
const onLastLine = (node) => { const { end } = caret(node); return !node.textContent.slice(end).includes('\n'); };

export function createEditor({ root, onChange, toast }) {
  let blocks = [], menu = null, readOnly = false;
  const list = el('div', 'blocks');
  const tools = el('div', 'kbbar'); tools.hidden = true;
  root.replaceChildren(list);
  document.body.append(tools);
  const changed = () => onChange?.(blocks);
  const rowOf = (id) => list.querySelector(`[data-id="${CSS.escape(id)}"]`);
  const textOf = (id) => rowOf(id)?.querySelector('.bt');
  const indexOf = (id) => blocks.findIndex((b) => b.id === id);

  function focusBlock(id, offset = 0) {
    const t = textOf(id);
    if (t) placeCaret(t, offset === Infinity ? t.textContent.length : offset);
    else rowOf(id)?.focus();
  }

  // ------------------------------------------------------------------ rendering

  function render(focus) {
    const hidden = hiddenByToggles(blocks);
    list.replaceChildren(...blocks.map((b, i) => row(b, i, hidden.has(i))));
    if (!blocks.length) list.append(placeholderRow());
    if (focus) requestAnimationFrame(() => focusBlock(focus.id, focus.offset));
  }

  function placeholderRow() {
    const r = el('div', 'bempty', 'Ketik sesuatu, atau "/" untuk memilih jenis blok…');
    r.addEventListener('click', () => { if (readOnly) return; blocks.push({ id: uid(), type: 'p', text: '' }); render({ id: blocks[0].id }); changed(); });
    return r;
  }

  function row(b, i, hide) {
    const r = el('div', `brow t-${b.type}${b.checked ? ' done' : ''}`);
    r.dataset.id = b.id; r.hidden = hide;
    r.style.setProperty('--ind', b.indent || 0);
    const handle = el('button', 'bhandle', '⋮⋮'); handle.title = 'Seret untuk memindah · klik untuk menu'; handle.tabIndex = -1;
    handle.draggable = true;
    handle.addEventListener('click', (e) => { e.preventDefault(); blockMenu(b.id, handle); });
    handle.addEventListener('dragstart', (e) => { e.dataTransfer.setData('text/x-block', b.id); e.dataTransfer.effectAllowed = 'move'; r.classList.add('dragging'); });
    handle.addEventListener('dragend', () => r.classList.remove('dragging'));
    r.addEventListener('dragover', (e) => { if (e.dataTransfer.types.includes('text/x-block')) { e.preventDefault(); r.classList.toggle('dropbelow', e.offsetY > r.offsetHeight / 2); r.classList.add('dropping'); } });
    r.addEventListener('dragleave', () => r.classList.remove('dropping', 'dropbelow'));
    r.addEventListener('drop', (e) => {
      const from = e.dataTransfer.getData('text/x-block'); r.classList.remove('dropping');
      if (!from || from === b.id) return;
      e.preventDefault();
      const below = r.classList.contains('dropbelow'); r.classList.remove('dropbelow');
      const [moved] = blocks.splice(indexOf(from), 1);
      blocks.splice(indexOf(b.id) + (below ? 1 : 0), 0, moved);
      render(); changed();
    });
    r.append(handle);

    if (b.type === 'divider') {
      const hr = el('div', 'bdivider'); r.tabIndex = 0;
      r.addEventListener('keydown', (e) => {
        if (e.key === 'Backspace' || e.key === 'Delete') { e.preventDefault(); removeBlock(b.id, -1); }
        if (e.key === 'Enter') { e.preventDefault(); insertAfter(b.id, { type: 'p', text: '' }); }
      });
      r.append(hr);
      return r;
    }
    if (b.type === 'todo') {
      const c = el('input', 'bcheck'); c.type = 'checkbox'; c.checked = !!b.checked; c.disabled = readOnly;
      c.addEventListener('change', () => { b.checked = c.checked; r.classList.toggle('done', c.checked); changed(); });
      r.append(c);
    } else if (b.type === 'bullet') r.append(el('span', 'bmark', ['•', '◦', '▪', '•', '◦'][b.indent || 0]));
    else if (b.type === 'number') r.append(el('span', 'bmark num', `${numberOf(blocks, i)}.`));
    else if (b.type === 'toggle') {
      const t = el('button', 'btoggle', b.open ? '▾' : '▸'); t.tabIndex = -1;
      t.addEventListener('click', () => { b.open = !b.open; render(); changed(); });
      r.append(t);
    } else if (b.type === 'callout') {
      const e = el('button', 'bemoji', b.emoji || '💡'); e.tabIndex = -1; e.title = 'Ganti ikon';
      e.addEventListener('click', () => { const i = ['💡', '⚠️', '✅', '❗', '📌', 'ℹ️', '🔥']; b.emoji = i[(i.indexOf(b.emoji || '💡') + 1) % i.length]; e.textContent = b.emoji; changed(); });
      r.append(e);
    }
    const t = el(b.type === 'code' ? 'pre' : 'div', 'bt');
    t.contentEditable = readOnly ? 'false' : (PLAIN ? 'plaintext-only' : 'true');
    t.spellcheck = b.type !== 'code';
    t.textContent = b.text || '';
    t.dataset.ph = { h1: 'Judul 1', h2: 'Judul 2', h3: 'Judul 3', todo: 'Tugas', bullet: 'Poin', number: 'Langkah', quote: 'Kutipan', code: 'Kode', callout: 'Catatan penting', toggle: 'Judul lipatan' }[b.type] || 'Ketik "/" untuk perintah';
    t.addEventListener('input', (e) => onInput(b, t, e));
    t.addEventListener('keydown', (e) => onKey(b, t, e));
    t.addEventListener('paste', (e) => onPaste(b, t, e));
    t.addEventListener('focus', () => showTools(b.id));
    t.addEventListener('blur', () => setTimeout(() => { if (!list.contains(document.activeElement)) tools.hidden = true; }, 150));
    r.append(t);
    if (b.type === 'todo') r.append(todoMeta(b));
    return r;
  }

  function todoMeta(b) {
    const m = el('span', 'bmeta');
    const due = el('label', `chip due${b.due && b.due < isoDay(new Date()) && !b.checked ? ' late' : ''}`, b.due ? `📅 ${dueLabel(b.due)}` : '📅');
    const d = el('input'); d.type = 'date'; d.value = b.due || ''; d.disabled = readOnly;
    d.addEventListener('change', () => { if (d.value) b.due = d.value; else delete b.due; changed(); render(); });
    due.append(d); due.title = 'Tenggat';
    const pr = el('button', `chip prio ${PRIORITY[b.priority]?.cls || ''}`, b.priority ? `⚑ ${PRIORITY[b.priority].label}` : '⚑'); pr.tabIndex = -1; pr.title = 'Prioritas';
    pr.addEventListener('click', () => { const p = nextPriority(b.priority); if (p) b.priority = p; else delete b.priority; changed(); render(); });
    m.append(due, pr);
    if (b.who) m.append(el('span', 'chip who', `👤 ${b.who}`));
    return m;
  }

  // ------------------------------------------------------------------ typing

  function onInput(b, t, e) {
    b.text = t.textContent;
    if (e.inputType === 'insertText' && e.data === ' ' && caret(t).start <= 4) {   // a Markdown shortcut typed at the start
      const s = shortcutFor(b.text);
      if (s) {
        b.type = s.type; b.text = s.rest;
        if (s.type === 'todo') b.checked = !!s.checked;
        render({ id: b.id, offset: 0 }); changed();
        if (s.type === 'divider') insertAfter(b.id, { type: 'p', text: '' });
        return;
      }
    }
    const { start } = caret(t), before = b.text.slice(0, start);
    const m = /(^|\s)\/([\p{L}\d]*)$/u.exec(before);
    if (m) openSlash(b, t, start - m[2].length - 1, m[2]); else closeMenu();
    changed();
  }

  function onKey(b, t, e) {
    if (menu?.keys && menu.keys(e)) return;
    const { start, end } = caret(t), len = t.textContent.length;
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      if (b.type === 'code' && !(e.ctrlKey || e.metaKey)) return;   // a new line inside code; Ctrl+Enter leaves it
      e.preventDefault();
      if (LIST_TYPES.has(b.type) && !b.text.trim()) { b.type = 'p'; render({ id: b.id }); changed(); return; }   // an empty item ends the list
      const after = b.text.slice(end);
      b.text = b.text.slice(0, start); t.textContent = b.text;
      const keep = LIST_TYPES.has(b.type) || b.type === 'toggle' ? (b.type === 'toggle' ? 'p' : b.type) : 'p';
      insertAfter(b.id, { type: keep, text: after, indent: b.type === 'toggle' ? (b.indent || 0) + 1 : b.indent }, 0);
      return;
    }
    if (e.key === 'Backspace' && start === 0 && end === 0) {
      e.preventDefault();
      if (b.type !== 'p') { b.type = 'p'; delete b.checked; render({ id: b.id, offset: 0 }); changed(); return; }
      if (b.indent) { b.indent -= 1; render({ id: b.id, offset: 0 }); changed(); return; }
      const i = indexOf(b.id), prev = blocks[i - 1];
      if (!prev) return;
      if (prev.type === 'divider') { blocks.splice(i - 1, 1); render({ id: b.id }); changed(); return; }
      const at = (prev.text || '').length;
      prev.text = (prev.text || '') + b.text;
      blocks.splice(i, 1); render({ id: prev.id, offset: at }); changed();
      return;
    }
    if (e.key === 'Delete' && start === len && end === len) {
      const i = indexOf(b.id), next = blocks[i + 1];
      if (!next) return;
      e.preventDefault();
      b.text += next.type === 'divider' ? '' : (next.text || '');
      blocks.splice(i + 1, 1); render({ id: b.id, offset: len }); changed();
      return;
    }
    if (e.key === 'Tab') {
      e.preventDefault();
      b.indent = Math.max(0, Math.min(4, (b.indent || 0) + (e.shiftKey ? -1 : 1)));
      if (!b.indent) delete b.indent;
      render({ id: b.id, offset: start }); changed();
      return;
    }
    if (e.key === 'ArrowUp' && onFirstLine(t)) { const p = visibleNeighbour(b.id, -1); if (p) { e.preventDefault(); focusBlock(p, Infinity); } }
    if (e.key === 'ArrowDown' && onLastLine(t)) { const n = visibleNeighbour(b.id, 1); if (n) { e.preventDefault(); focusBlock(n, 0); } }
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && b.type === 'todo') { e.preventDefault(); b.checked = !b.checked; render({ id: b.id, offset: start }); changed(); }
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) { e.preventDefault(); move(b.id, e.key === 'ArrowUp' ? -1 : 1); }
  }

  function visibleNeighbour(id, dir) {
    const hidden = hiddenByToggles(blocks);
    for (let i = indexOf(id) + dir; i >= 0 && i < blocks.length; i += dir) if (!hidden.has(i)) return blocks[i].id;
    return null;
  }

  function onPaste(b, t, e) {
    const text = e.clipboardData?.getData('text/plain') ?? '';
    e.preventDefault();
    if (!text.includes('\n')) { document.execCommand('insertText', false, text); return; }
    const parsed = parseLines(text).map((x) => ({ id: uid(), ...x }));
    if (!parsed.length) return;
    const i = indexOf(b.id);
    const replace = !b.text.trim();
    blocks.splice(replace ? i : i + 1, replace ? 1 : 0, ...parsed);
    const last = parsed[parsed.length - 1];
    render({ id: last.id, offset: Infinity }); changed();
    toast?.(`${parsed.length} blok ditempel.`);
  }

  // ------------------------------------------------------------------ structure

  function insertAfter(id, b, offset = 0) {
    const nb = { text: '', ...b, id: uid() };
    if (!nb.indent) delete nb.indent;
    blocks.splice(indexOf(id) + 1, 0, nb);
    render({ id: nb.id, offset }); changed();
    return nb;
  }
  function removeBlock(id, focusDir = -1) {
    const i = indexOf(id);
    if (i < 0) return;
    blocks.splice(i, 1);
    const f = blocks[Math.max(0, focusDir < 0 ? i - 1 : i)];
    render(f ? { id: f.id, offset: Infinity } : null); changed();
  }
  function move(id, dir) {
    const i = indexOf(id), j = i + dir;
    if (j < 0 || j >= blocks.length) return;
    [blocks[i], blocks[j]] = [blocks[j], blocks[i]];
    render({ id, offset: Infinity }); changed();
  }
  function setType(id, type) {
    const b = blocks[indexOf(id)];
    if (!b) return;
    b.type = type;
    if (type !== 'todo') { delete b.checked; delete b.due; delete b.priority; }
    render({ id, offset: Infinity }); changed();
    if (type === 'divider') insertAfter(id, { type: 'p', text: '' });
  }

  // ------------------------------------------------------------------ menus

  function closeMenu() { menu?.el.remove(); menu = null; }
  function placeMenu(m, anchor) {
    const r = anchor.getBoundingClientRect();
    document.body.append(m);
    const top = r.bottom + 6 + m.offsetHeight > innerHeight ? Math.max(8, r.top - m.offsetHeight - 6) : r.bottom + 6;
    m.style.left = `${Math.max(8, Math.min(r.left, innerWidth - m.offsetWidth - 8))}px`; m.style.top = `${top}px`;
  }

  function openSlash(b, t, slashAt, q) {
    const items = filterSlash(q);
    if (!items.length) { closeMenu(); return; }
    closeMenu();
    const m = el('div', 'menu slash');
    let sel = 0;
    const pick = (type) => {
      const end = caret(t).start;
      b.text = b.text.slice(0, slashAt) + b.text.slice(end);
      closeMenu();
      if (!b.text.trim() || b.type === 'p' && !b.text.slice(0, slashAt).trim()) setType(b.id, type);
      else insertAfter(b.id, { type, text: '' });
    };
    const draw = () => m.replaceChildren(el('div', 'mlabel', 'Jenis blok'), ...items.map((it, k) => {
      const x = el('button', `mitem${k === sel ? ' on' : ''}`); x.tabIndex = -1;
      x.append(el('span', 'micon', it.icon), el('span', 'mtext'));
      x.lastChild.append(el('b', null, it.label), el('small', null, it.md ? `${it.hint} · ${it.md}` : it.hint));
      x.addEventListener('pointerdown', (e) => { e.preventDefault(); pick(it.type); });
      return x;
    }));
    draw();
    menu = { el: m, keys: (e) => {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); sel = (sel + (e.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length; draw(); m.querySelector('.on')?.scrollIntoView({ block: 'nearest' }); return true; }
      if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); pick(items[sel].type); return true; }
      if (e.key === 'Escape') { e.preventDefault(); closeMenu(); return true; }
      return false;
    } };
    placeMenu(m, t);
  }

  function blockMenu(id, anchor) {
    closeMenu();
    const b = blocks[indexOf(id)];
    const m = el('div', 'menu');
    const item = (label, fn, cls = '') => { const x = el('button', `mitem ${cls}`, label); x.addEventListener('click', () => { closeMenu(); fn(); }); return x; };
    m.append(el('div', 'mlabel', 'Ubah jadi'));
    const grid = el('div', 'mgrid');
    for (const [type, v] of Object.entries(BLOCK_TYPES)) {
      const x = el('button', `mchip${b.type === type ? ' on' : ''}`, v.icon); x.title = v.label;
      x.addEventListener('click', () => { closeMenu(); setType(id, type); });
      grid.append(x);
    }
    m.append(grid,
      item('↑ Pindah ke atas', () => move(id, -1)), item('↓ Pindah ke bawah', () => move(id, 1)),
      item('⇥ Menjorok', () => { b.indent = Math.min(4, (b.indent || 0) + 1); render(); changed(); }),
      item('⇤ Kurangi jorok', () => { b.indent = Math.max(0, (b.indent || 0) - 1); if (!b.indent) delete b.indent; render(); changed(); }),
      item('⧉ Duplikat', () => insertAfter(id, { ...b, id: undefined }, Infinity)),
      item('🗑 Hapus', () => removeBlock(id), 'bad'));
    placeMenu(m, anchor);
    setTimeout(() => addEventListener('pointerdown', function off(e) { if (!m.contains(e.target)) { closeMenu(); removeEventListener('pointerdown', off); } }), 0);
  }

  // ------------------------------------------------------------------ the phone's toolbar over the keyboard

  function showTools(id) {
    if (readOnly || matchMedia('(min-width: 900px)').matches) return;
    const b = () => blocks[indexOf(id)];
    const btn = (label, fn, title) => { const x = el('button', null, label); x.title = title; x.addEventListener('pointerdown', (e) => { e.preventDefault(); fn(); }); return x; };
    tools.replaceChildren(
      btn('＋', () => { const t = textOf(id); if (t) openSlash(b(), t, caret(t).start, ''); }, 'Jenis blok'),
      btn('☑', () => setType(id, b().type === 'todo' ? 'p' : 'todo'), 'Tugas'),
      btn('•', () => setType(id, b().type === 'bullet' ? 'p' : 'bullet'), 'Poin'),
      btn('H', () => setType(id, { p: 'h1', h1: 'h2', h2: 'h3' }[b().type] || 'p'), 'Judul'),
      btn('⇥', () => { const x = b(); x.indent = Math.min(4, (x.indent || 0) + 1); render({ id, offset: Infinity }); changed(); }, 'Menjorok'),
      btn('⇤', () => { const x = b(); x.indent = Math.max(0, (x.indent || 0) - 1); if (!x.indent) delete x.indent; render({ id, offset: Infinity }); changed(); }, 'Kurangi jorok'),
      btn('↑', () => move(id, -1), 'Ke atas'), btn('↓', () => move(id, 1), 'Ke bawah'),
      btn('🗑', () => removeBlock(id), 'Hapus blok'));
    tools.hidden = false;
  }
  if (window.visualViewport) {   // keep the toolbar right above the phone's keyboard
    const stick = () => { tools.style.bottom = `${Math.max(0, innerHeight - visualViewport.height - visualViewport.offsetTop)}px`; };
    visualViewport.addEventListener('resize', stick); visualViewport.addEventListener('scroll', stick);
  }

  return {
    load(next, opts = {}) {
      closeMenu();
      readOnly = !!opts.readOnly;
      blocks = (next || []).map((b) => ({ ...b, id: b.id || uid() }));
      render();
    },
    get blocks() { return blocks; },
    focusEnd() {
      if (!blocks.length || blocks[blocks.length - 1].text) blocks.push({ id: uid(), type: 'p', text: '' });
      render({ id: blocks[blocks.length - 1].id, offset: Infinity });
    },
    addTodo(text = '') { const b = { id: uid(), type: 'todo', text }; blocks.push(b); render({ id: b.id, offset: Infinity }); changed(); },
  };
}
