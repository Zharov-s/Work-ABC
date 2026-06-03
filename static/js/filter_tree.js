/**
 * filter_tree.js — Reusable hierarchical filter component.
 *
 * Dependencies: filter_data.js (FILTER_GROUPS constant)
 *
 * Usage:
 *   const state = new FilterState(FILTER_GROUPS);
 *   const tree  = new FilterTree(document.getElementById('ft-root'), state);
 *   tree.onChange(codes => { hiddenInput.value = codes.join(','); });
 *
 * FilterState manages selection as a flat Set of selected OKVED IDs.
 * Group / VRI states are derived from their children — never stored separately.
 *
 * FilterTree renders the DOM tree and wires events.
 * Expand/collapse and selection are always independent actions.
 */

// ─── FilterState ─────────────────────────────────────────────────────────────

class FilterState {
  constructor(groups) {
    this.groups = groups;
    this._selected = new Set(); // OKVED IDs only (leaf nodes)
  }

  // ── Lookup helpers ───────────────────────────────────────────────────────

  _allOkvedsForGroup(group) {
    return group.children.flatMap(vri => vri.children.map(o => o.id));
  }

  _allOkvedsForVRI(vri) {
    return vri.children.map(o => o.id);
  }

  findGroup(id) {
    return this.groups.find(g => g.id === id) || null;
  }

  findVRI(id) {
    for (const g of this.groups) {
      const v = g.children.find(v => v.id === id);
      if (v) return v;
    }
    return null;
  }

  findOkved(id) {
    for (const g of this.groups) {
      for (const v of g.children) {
        const o = v.children.find(o => o.id === id);
        if (o) return o;
      }
    }
    return null;
  }

  // ── State queries — returns 'all' | 'some' | 'none' ─────────────────────

  groupState(group) {
    const ids = this._allOkvedsForGroup(group);
    if (!ids.length) return 'none';
    const n = ids.filter(id => this._selected.has(id)).length;
    if (n === 0) return 'none';
    return n === ids.length ? 'all' : 'some';
  }

  vriState(vri) {
    const ids = this._allOkvedsForVRI(vri);
    if (!ids.length) return 'none';
    const n = ids.filter(id => this._selected.has(id)).length;
    if (n === 0) return 'none';
    return n === ids.length ? 'all' : 'some';
  }

  okvedState(okved) {
    return this._selected.has(okved.id) ? 'all' : 'none';
  }

  // ── Mutations ────────────────────────────────────────────────────────────

  setGroup(group, checked) {
    this._allOkvedsForGroup(group).forEach(id =>
      checked ? this._selected.add(id) : this._selected.delete(id)
    );
  }

  setVRI(vri, checked) {
    this._allOkvedsForVRI(vri).forEach(id =>
      checked ? this._selected.add(id) : this._selected.delete(id)
    );
  }

  setOkved(okved, checked) {
    checked ? this._selected.add(okved.id) : this._selected.delete(okved.id);
  }

  clearAll() {
    this._selected.clear();
  }

  // ── Serialization ────────────────────────────────────────────────────────

  getSelectedCodes() {
    const codes = [];
    for (const g of this.groups) {
      for (const v of g.children) {
        for (const o of v.children) {
          if (this._selected.has(o.id)) codes.push(o.code);
        }
      }
    }
    return codes;
  }

  getTotalSelected() {
    return this._selected.size;
  }

  hasSelection() {
    return this._selected.size > 0;
  }

  loadFromCodes(codeArray) {
    this._selected.clear();
    const codeSet = new Set(codeArray);
    for (const g of this.groups) {
      for (const v of g.children) {
        for (const o of v.children) {
          if (codeSet.has(o.code)) this._selected.add(o.id);
        }
      }
    }
  }
}


// ─── FilterTree ───────────────────────────────────────────────────────────────

class FilterTree {
  constructor(container, state) {
    this.container = container;
    this.state = state;
    this._expanded = new Set();
    this._changeCb = null;
    this._build();
  }

  onChange(cb) {
    this._changeCb = cb;
    return this;
  }

  // ── DOM construction ─────────────────────────────────────────────────────

  _build() {
    this.container.innerHTML = '';
    for (const group of this.state.groups) {
      this.container.appendChild(this._buildGroup(group));
    }
    this._syncAllCheckboxes();
  }

  _buildGroup(group) {
    const wrap = document.createElement('div');
    wrap.className = 'ft-group';
    wrap.dataset.id = group.id;
    wrap.appendChild(this._buildRow(group.id, group.title, 0, 'group', null));

    const ch = document.createElement('div');
    ch.className = 'ft-children';
    ch.id = `ft-ch-${group.id}`;
    ch.hidden = !this._expanded.has(group.id);
    group.children.forEach(vri => ch.appendChild(this._buildVRI(vri)));
    wrap.appendChild(ch);
    return wrap;
  }

  _buildVRI(vri) {
    const wrap = document.createElement('div');
    wrap.className = 'ft-vri';
    wrap.dataset.id = vri.id;
    wrap.appendChild(this._buildRow(vri.id, vri.title, 1, 'vri', vri.code));

    const ch = document.createElement('div');
    ch.className = 'ft-children';
    ch.id = `ft-ch-${vri.id}`;
    ch.hidden = !this._expanded.has(vri.id);
    vri.children.forEach(okved => ch.appendChild(this._buildOkved(okved)));
    wrap.appendChild(ch);
    return wrap;
  }

  _buildOkved(okved) {
    const wrap = document.createElement('div');
    wrap.className = 'ft-okved';
    wrap.dataset.id = okved.id;
    wrap.appendChild(this._buildRow(okved.id, okved.title, 2, 'okved', okved.code));
    return wrap;
  }

  _buildRow(id, title, level, type, code) {
    const row = document.createElement('div');
    row.className = `ft-row ft-row--${type}`;
    row.dataset.id   = id;
    row.dataset.type = type;

    // Indentation spacer
    const indent = document.createElement('span');
    indent.className = 'ft-indent';
    indent.style.width = `${level * 18}px`;
    indent.style.flexShrink = '0';
    row.appendChild(indent);

    // Expand arrow (group + vri only) — clicking label also triggers expand
    if (type !== 'okved') {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'ft-expand';
      btn.dataset.expandId = id;
      btn.setAttribute('aria-label', 'Развернуть');
      btn.innerHTML = `<svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true"><path d="M3 1.5 6.5 5 3 8.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
      btn.addEventListener('click', e => { e.stopPropagation(); this._toggleExpand(id); });
      row.appendChild(btn);
    } else {
      const sp = document.createElement('span');
      sp.className = 'ft-expand-spacer';
      row.appendChild(sp);
    }

    // Custom checkbox — clicking it only changes selection, never expands
    const check = document.createElement('span');
    check.className = 'ft-check';
    check.dataset.checkId = id;
    check.setAttribute('role', 'checkbox');
    check.setAttribute('tabindex', '0');
    check.setAttribute('aria-checked', 'false');
    check.addEventListener('click', e => { e.stopPropagation(); this._handleCheck(id, type); });
    check.addEventListener('keydown', e => {
      if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); this._handleCheck(id, type); }
    });
    row.appendChild(check);

    // Label — clicking expands for group/vri, no action for okved
    const label = document.createElement('span');
    label.className = 'ft-label';
    if (code) {
      const badge = document.createElement('span');
      badge.className = 'ft-code';
      badge.textContent = code;
      label.appendChild(badge);
    }
    const txt = document.createElement('span');
    txt.className = 'ft-title';
    txt.textContent = title;
    label.appendChild(txt);

    if (type !== 'okved') {
      label.style.cursor = 'pointer';
      label.addEventListener('click', e => { e.stopPropagation(); this._toggleExpand(id); });
    }

    row.appendChild(label);
    return row;
  }

  // ── Expand / Collapse ────────────────────────────────────────────────────

  _toggleExpand(id) {
    this._expanded.has(id) ? this._expanded.delete(id) : this._expanded.add(id);
    const ch = document.getElementById(`ft-ch-${id}`);
    if (ch) ch.hidden = !this._expanded.has(id);
    this._syncExpandBtn(id);
  }

  expandGroup(id) {
    if (!this._expanded.has(id)) this._toggleExpand(id);
  }

  expandSelected() {
    for (const group of this.state.groups) {
      if (this.state.groupState(group) !== 'none') {
        this.expandGroup(group.id);
        for (const vri of group.children) {
          if (this.state.vriState(vri) !== 'none') {
            this.expandGroup(vri.id);
          }
        }
      }
    }
  }

  _syncExpandBtn(id) {
    const btn = this.container.querySelector(`[data-expand-id="${id}"]`);
    if (!btn) return;
    const isOpen = this._expanded.has(id);
    btn.classList.toggle('ft-expand--open', isOpen);
    btn.setAttribute('aria-label', isOpen ? 'Свернуть' : 'Развернуть');
  }

  // ── Selection handling ───────────────────────────────────────────────────

  _handleCheck(id, type) {
    const st = this.state;

    if (type === 'group') {
      const group = st.findGroup(id);
      if (group) st.setGroup(group, st.groupState(group) !== 'all');
    } else if (type === 'vri') {
      const vri = st.findVRI(id);
      if (vri) st.setVRI(vri, st.vriState(vri) !== 'all');
    } else {
      const okved = st.findOkved(id);
      if (okved) st.setOkved(okved, st.okvedState(okved) !== 'all');
    }

    this._syncAllCheckboxes();
    if (this._changeCb) this._changeCb(st.getSelectedCodes());
  }

  _syncAllCheckboxes() {
    for (const group of this.state.groups) {
      this._applyCheckState(group.id, this.state.groupState(group));
      for (const vri of group.children) {
        this._applyCheckState(vri.id, this.state.vriState(vri));
        for (const okved of vri.children) {
          this._applyCheckState(okved.id, this.state.okvedState(okved));
        }
      }
    }
  }

  _applyCheckState(id, state) {
    const el = this.container.querySelector(`[data-check-id="${id}"]`);
    if (!el) return;
    el.dataset.state = state;
    el.setAttribute('aria-checked', state === 'all' ? 'true' : state === 'some' ? 'mixed' : 'false');
  }

  // ── Public refresh after external state change ───────────────────────────

  refresh() {
    this._syncAllCheckboxes();
  }
}
