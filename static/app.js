// Umumiy yordamchi funksiyalar
const App = {
  money(v) {
    const n = Math.round(Number(v) || 0);
    return n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
  },
  num(v) {
    const n = parseFloat(String(v ?? '').replace(/\s/g, '').replace(',', '.'));
    return isNaN(n) ? 0 : n;
  },
  qty(v) {
    return String(parseFloat(Number(v).toFixed(3)));
  },
  csrf() {
    const m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : (document.querySelector('[name=csrfmiddlewaretoken]') || {}).value;
  },
  escape(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  },
  debounce(fn, ms = 200) {
    let t;
    return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
  },
  async getJSON(url) {
    const r = await fetch(url, {headers: {'X-Requested-With': 'fetch'}});
    return r.json();
  },
};

// <form data-confirm="Matn"> - birinchi bosishda tugma "tasdiqlang" holatiga o'tadi, ikkinchisida yuboradi
document.addEventListener('submit', e => {
  const form = e.target;
  if (!form.dataset.confirm || form.dataset.confirmed) return;
  e.preventDefault();
  const btn = form.querySelector('button');
  form.dataset.confirmed = '1';
  btn.classList.add('btn-danger');
  btn.classList.remove('btn-outline-danger');
  btn.title = form.dataset.confirm;
  btn.insertAdjacentText('beforeend', ' ' + form.dataset.confirm);
  setTimeout(() => {
    if (!form.isConnected) return;
    delete form.dataset.confirmed;
    btn.classList.remove('btn-danger');
    btn.classList.add('btn-outline-danger');
    btn.lastChild.remove();
  }, 4000);
});

/**
 * Tovar tanlash maydoni (nomi bo'yicha qidiruv).
 * <div class="picker" data-picker>
 *   <input class="form-control" data-picker-input> <input type="hidden" name="product">
 * </div>
 */
class ProductPicker {
  constructor(root, {url, onSelect, renderMeta} = {}) {
    this.root = root;
    this.url = url || root.dataset.url;
    this.input = root.querySelector('[data-picker-input]');
    this.hidden = root.querySelector('input[type=hidden]');
    this.onSelect = onSelect;
    this.renderMeta = renderMeta || (() => '');
    this.menu = document.createElement('div');
    this.menu.className = 'list-group picker-menu shadow d-none';
    root.appendChild(this.menu);
    this.items = [];
    this.index = -1;

    this.input.addEventListener('input', () => {
      clearTimeout(this.timer);
      this.timer = setTimeout(() => this.search(), 200);
    });
    this.input.addEventListener('keydown', e => this.keydown(e));
    this.input.addEventListener('focus', () => { if (this.items.length) this.menu.classList.remove('d-none'); });
    document.addEventListener('click', e => { if (!root.contains(e.target)) this.close(); });
  }

  async search(exactEnter = false) {
    clearTimeout(this.timer);
    const q = this.input.value.trim();
    if (this.hidden) this.hidden.value = '';
    if (!q) { this.close(); return; }
    // Har bir so'rovga raqam beramiz: kechikib kelgan eski javob yangisining ustiga yozilmaydi
    const seq = this.seq = (this.seq || 0) + 1;
    const data = await App.getJSON(`${this.url}?q=${encodeURIComponent(q)}`);
    if (seq !== this.seq) return;
    this.items = data.results;
    this.query = q;
    this.index = this.items.length ? 0 : -1;
    // Enter bosilganda faqat bitta tovar topilsa, darhol tanlaymiz
    if (exactEnter && this.items.length === 1) { this.select(this.items[0]); return; }
    this.render();
  }

  render() {
    if (!this.items.length) {
      this.menu.innerHTML = '<div class="list-group-item text-muted small">—</div>';
    } else {
      this.menu.innerHTML = this.items.map((p, i) => `
        <button type="button" class="list-group-item list-group-item-action ${i === this.index ? 'active' : ''}" data-i="${i}">
          <div class="d-flex justify-content-between"><span>${App.escape(p.name)}</span>
          <small>${p.sale_price != null ? App.money(p.sale_price) : ''}</small></div>
          <small class="${i === this.index ? '' : 'text-muted'}">${this.renderMeta(p)}</small>
        </button>`).join('');
      this.menu.querySelectorAll('[data-i]').forEach(b =>
        b.addEventListener('click', () => this.select(this.items[+b.dataset.i])));
    }
    this.menu.classList.remove('d-none');
  }

  keydown(e) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!this.items.length) return;
      this.index = (this.index + (e.key === 'ArrowDown' ? 1 : -1) + this.items.length) % this.items.length;
      this.render();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      // Menyu hozirgi matn bo'yicha topilgan bo'lsagina undan tanlaymiz,
      // aks holda (matn o'zgargan, natija eskirgan) qaytadan qidiramiz.
      const menuOpen = !this.menu.classList.contains('d-none');
      const fresh = this.query === this.input.value.trim();
      if (menuOpen && fresh && this.items[this.index]) this.select(this.items[this.index]);
      else this.search(true);
    } else if (e.key === 'Escape') {
      this.close();
    }
  }

  select(p) {
    clearTimeout(this.timer);
    this.seq = (this.seq || 0) + 1;  // kutilayotgan qidiruv javoblarini bekor qilamiz
    if (this.hidden) this.hidden.value = p.id;
    this.input.value = p.name;
    this.close();
    if (this.onSelect) this.onSelect(p, this);
  }

  close() { this.menu.classList.add('d-none'); }

  clear() {
    this.input.value = '';
    if (this.hidden) this.hidden.value = '';
    this.items = [];
    this.close();
  }
}
