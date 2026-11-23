// Universal preview panel. The backend normalises every format to PDF,
// so this single component (PDF.js) previews Word, Excel, PowerPoint, TXT and PDF alike.
import * as pdfjsLib from './vendor/pdfjs/pdf.min.mjs';

pdfjsLib.GlobalWorkerOptions.workerSrc = new URL('./vendor/pdfjs/pdf.worker.min.mjs', import.meta.url).href;

const $ = (id) => document.getElementById(id);

export class FilePreviewPanel {
  constructor() {
    this.modal = $('preview-modal');
    this.box = $('preview-box');
    this.wrap = $('pv-wrap');
    this.canvas = $('pv-canvas');
    this.status = $('pv-status');
    this.pageInput = $('pv-page');
    this.pdf = null;
    this.page = 1;
    this.scale = 1;
    this.fitMode = true;
    this.renderTask = null;
    this.token = 0;

    $('pv-close').onclick = () => this.close();
    $('pv-prev').onclick = () => this.goto(this.page - 1);
    $('pv-next').onclick = () => this.goto(this.page + 1);
    $('pv-zoom-in').onclick = () => this.zoom(1.25);
    $('pv-zoom-out').onclick = () => this.zoom(0.8);
    $('pv-fit').onclick = () => { this.fitMode = true; this.render(); };
    $('pv-full').onclick = () => this.toggleFullscreen();
    this.pageInput.onchange = () => this.goto(parseInt(this.pageInput.value, 10));
    this.modal.addEventListener('mousedown', (e) => { if (e.target === this.modal) this.close(); });
    document.addEventListener('keydown', (e) => {
      if (this.modal.hidden || e.target.tagName === 'INPUT') return;
      if (e.key === 'ArrowRight' || e.key === 'PageDown') this.goto(this.page + 1);
      if (e.key === 'ArrowLeft' || e.key === 'PageUp') this.goto(this.page - 1);
      if (e.key === 'Escape' && !document.fullscreenElement) this.close();
    });
    const refit = () => { if (!this.modal.hidden && this.fitMode && this.pdf) this.render(); };
    window.addEventListener('resize', refit);
    document.addEventListener('fullscreenchange', () => setTimeout(refit, 50));
  }

  async open({ url, name, type }) {
    await this.#reset();
    $('pv-name').textContent = name;
    $('pv-type').textContent = type;
    $('pv-pages').textContent = '0';
    this.pageInput.value = 1;
    this.status.textContent = 'Loading…';
    this.status.hidden = false;
    this.canvas.hidden = true;
    this.modal.hidden = false;
    this.fitMode = true;
    this.page = 1;
    try {
      let token = ''; try { token = localStorage.getItem('cfg_token') || ''; } catch { /* ignore */ }
      const doc = await pdfjsLib.getDocument({ url, withCredentials: true, httpHeaders: token ? { Authorization: `Bearer ${token}` } : undefined }).promise;
      this.pdf = doc;
      $('pv-pages').textContent = doc.numPages;
      this.pageInput.max = doc.numPages;
      await this.render();
    } catch (err) {
      console.error('Preview failed', err);
      this.status.textContent = 'Unable to display this document.';
      this.status.hidden = false;
    }
  }

  async close() {
    if (document.fullscreenElement) { try { await document.exitFullscreen(); } catch { /* ignore */ } }
    this.modal.hidden = true;
    await this.#reset();
  }

  async #reset() {
    this.token++;
    if (this.renderTask) { try { this.renderTask.cancel(); } catch { /* ignore */ } this.renderTask = null; }
    if (this.pdf) { try { await this.pdf.destroy(); } catch { /* ignore */ } this.pdf = null; }
  }

  goto(n) {
    if (!this.pdf || !Number.isFinite(n)) { this.pageInput.value = this.page; return; }
    this.page = Math.min(Math.max(1, n), this.pdf.numPages);
    this.wrap.scrollTop = 0;
    this.render();
  }

  zoom(factor) {
    this.fitMode = false;
    this.scale = Math.min(5, Math.max(0.25, this.scale * factor));
    this.render();
  }

  toggleFullscreen() {
    if (document.fullscreenElement) document.exitFullscreen();
    else this.box.requestFullscreen?.().catch(() => {});
  }

  async render() {
    if (!this.pdf) return;
    const my = ++this.token;
    if (this.renderTask) { try { this.renderTask.cancel(); } catch { /* ignore */ } }
    const pdf = this.pdf;
    const page = await pdf.getPage(this.page);
    if (my !== this.token) return;
    if (this.fitMode) {
      const natural = page.getViewport({ scale: 1 }).width;
      this.scale = Math.max(0.1, (this.wrap.clientWidth - 34) / natural);
    }
    const viewport = page.getViewport({ scale: this.scale });
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width = Math.floor(viewport.width * dpr);
    this.canvas.height = Math.floor(viewport.height * dpr);
    this.canvas.style.width = `${Math.floor(viewport.width)}px`;
    this.canvas.style.height = `${Math.floor(viewport.height)}px`;
    const ctx = this.canvas.getContext('2d');
    this.renderTask = page.render({
      canvasContext: ctx, viewport,
      transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null,
    });
    try {
      await this.renderTask.promise;
    } catch (e) {
      if (e?.name === 'RenderingCancelledException') return;
      throw e;
    }
    if (my !== this.token) return;
    this.status.hidden = true;
    this.canvas.hidden = false;
    this.pageInput.value = this.page;
    $('pv-zoom').textContent = `${Math.round(this.scale * 100)}%`;
    $('pv-prev').disabled = this.page <= 1;
    $('pv-next').disabled = this.page >= pdf.numPages;
  }
}
