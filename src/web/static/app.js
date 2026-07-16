const themeButtons = document.querySelectorAll('[data-theme-choice]');

function applyTheme(theme) {
  if (theme === 'auto') {
    delete document.documentElement.dataset.theme;
    localStorage.removeItem('d20-theme');
  } else {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('d20-theme', theme);
  }
  themeButtons.forEach((button) => {
    button.setAttribute('aria-pressed', String(button.dataset.themeChoice === theme));
  });
}

themeButtons.forEach((button) => {
  button.addEventListener('click', () => applyTheme(button.dataset.themeChoice));
});
applyTheme(localStorage.getItem('d20-theme') || 'auto');

const scheduleForm = document.querySelector('[data-local-schedule]');
if (scheduleForm) {
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'локальный';
  document.querySelector('[data-browser-timezone]').textContent =
    `Время вводится в часовом поясе браузера: ${zone}`;

  scheduleForm.addEventListener('submit', (event) => {
    const [day, month, year] = scheduleForm.elements.local_date.value.split('.').map(Number);
    const [hour, minute] = scheduleForm.elements.local_time.value.split(':').map(Number);
    const local = new Date(year, month - 1, day, hour, minute);
    const valid = local.getFullYear() === year
      && local.getMonth() === month - 1
      && local.getDate() === day
      && local.getHours() === hour
      && local.getMinutes() === minute;
    if (!valid) {
      event.preventDefault();
      scheduleForm.elements.local_date.setCustomValidity('Проверьте дату и время');
      scheduleForm.elements.local_date.reportValidity();
      return;
    }
    scheduleForm.elements.local_date.setCustomValidity('');
    scheduleForm.elements.scheduled_at.value = local.toISOString();
  });
}

document.querySelectorAll('form').forEach((form) => {
  form.addEventListener('submit', (event) => {
    const message = form.dataset.confirm;
    if (message && !window.confirm(message)) {
      event.preventDefault();
      return;
    }
    if (event.defaultPrevented || !form.checkValidity()) return;
    const button = form.querySelector('button[type="submit"]');
    if (button) {
      button.disabled = true;
      button.dataset.label = button.textContent;
      button.textContent = 'Сохраняем…';
    }
  });
});
