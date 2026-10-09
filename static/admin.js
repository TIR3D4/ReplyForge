(() => {
  const root = document.documentElement;
  try { root.dataset.theme = localStorage.getItem('replyforge-theme') || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'); } catch (_) {}
  document.querySelector('#theme-toggle')?.addEventListener('click', () => {
    root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
    try { localStorage.setItem('replyforge-theme', root.dataset.theme); } catch (_) {}
  });
  document.querySelectorAll('.image-editor').forEach(editor => {
    const canvas = editor.querySelector('canvas'); const context = canvas.getContext('2d');
    const submit = editor.querySelector('[type="submit"]');
    const consent = editor.querySelector('[name="privacy_reviewed"]');
    let original = null; let start = null; let revision = 0;
    submit.disabled = true;
    const reset = () => {
      consent.checked = false;
      if (original) { context.fillStyle = '#fff'; context.fillRect(0,0,canvas.width,canvas.height); context.drawImage(original,0,0,canvas.width,canvas.height); }
    };
    editor.querySelector('.image-input').addEventListener('change', async event => {
      const current = ++revision;
      consent.checked = false; submit.disabled = true; canvas.hidden = true;
      delete canvas.dataset.loaded; original?.close(); original = null;
      const file = event.target.files[0];
      const invalid = () => { document.querySelector('#form-status').textContent = root.lang === 'fa' ? 'تصویر معتبر PNG، JPEG یا WebP با حجم حداکثر ۱۰ مگابایت انتخاب کنید.' : 'Choose a valid PNG, JPEG or WebP image up to 10 MiB.'; };
      if (!file) return;
      if (file.size > 10 * 1024 * 1024 || !['image/png','image/jpeg','image/webp'].includes(file.type)) { invalid(); return; }
      try {
        const bitmap = await createImageBitmap(file);
        if (current !== revision) { bitmap.close(); return; }
        if (bitmap.width * bitmap.height > 40000000) { bitmap.close(); invalid(); return; }
        original = bitmap;
        const scale = Math.min(1,1600/Math.max(bitmap.width,bitmap.height));
        canvas.width = Math.max(1,Math.round(bitmap.width*scale)); canvas.height = Math.max(1,Math.round(bitmap.height*scale));
        canvas.hidden = false; canvas.dataset.loaded = 'true'; reset(); submit.disabled = false;
      } catch (_) { if (current === revision) invalid(); }
    });
    const point = event => { const box = canvas.getBoundingClientRect(); return [(event.clientX-box.left)*canvas.width/box.width,(event.clientY-box.top)*canvas.height/box.height]; };
    canvas.addEventListener('pointercancel', () => { start = null; });
    canvas.addEventListener('pointerdown', event => { consent.checked = false; start = point(event); canvas.setPointerCapture(event.pointerId); });
    canvas.addEventListener('pointerup', event => { if (!start) return; const end = point(event); context.fillStyle = '#000'; context.fillRect(Math.min(start[0],end[0]),Math.min(start[1],end[1]),Math.abs(end[0]-start[0]),Math.abs(end[1]-start[1])); start = null; });
    editor.querySelector('.image-reset').addEventListener('click', reset);
  });
  document.querySelectorAll('form[method="post"]').forEach(form => {
    form.addEventListener('submit', event => {
      if (event.defaultPrevented) return;
      if (form.dataset.imageEditor) {
        const canvas = form.closest('.image-editor').querySelector('canvas');
        if (!canvas.dataset.loaded) { event.preventDefault(); return; }
        const encoded = canvas.toDataURL('image/png');
        if (encoded.length > 2800000) { event.preventDefault(); document.querySelector('#form-status').textContent = root.lang === 'fa' ? 'تصویر بزرگ است؛ یک تصویر کوچک‌تر انتخاب کنید.' : 'Image is too large. Choose a smaller image.'; return; }
        form.querySelector('[name="image_base64"]').value = encoded;
      }
      const status = document.querySelector('#form-status');
      if (status) status.textContent = root.lang === 'fa' ? 'در حال پردازش…' : 'Processing…';
      // Preserve the clicked button's name/value in the submitted form.
      if (event.submitter?.name) {
        const field = document.createElement('input'); field.type = 'hidden';
        field.name = event.submitter.name; field.value = event.submitter.value; form.append(field);
      }
      form.querySelectorAll('button[type="submit"],button:not([type])').forEach(button => button.disabled = true);
    });
  });
})();
