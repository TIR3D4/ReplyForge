(() => {
  const root = document.documentElement;
  try { root.dataset.theme = localStorage.getItem('replyforge-theme') || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'); } catch (_) {}
  document.querySelector('#theme-toggle')?.addEventListener('click', () => {
    root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
    try { localStorage.setItem('replyforge-theme', root.dataset.theme); } catch (_) {}
  });
  document.querySelectorAll('form[method="post"]').forEach(form => {
    form.addEventListener('submit', event => {
      if (event.defaultPrevented) return;
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
