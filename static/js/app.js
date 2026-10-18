/* ============================================================
   معمل صدارة — app.js
   Shared behaviour for the dashboard shell (sidebar, modal, flash)
   ============================================================ */

document.addEventListener('DOMContentLoaded', () => {
  if (window.lucide) lucide.createIcons();

  initSidebar();
  initDeleteModal();
  initFlashAutoDismiss();
});

/* ── Sidebar mobile toggle ───────────────────────────────── */
function initSidebar() {
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('sidebarOverlay');
  const toggle = document.getElementById('sidebarToggle');

  if (!sidebar) return;

  const open = () => {
    sidebar.classList.add('open');
    overlay && overlay.classList.add('open');
  };
  const close = () => {
    sidebar.classList.remove('open');
    overlay && overlay.classList.remove('open');
  };

  toggle && toggle.addEventListener('click', open);
  overlay && overlay.addEventListener('click', close);
}

/* ── Delete confirmation modal ───────────────────────────── */
let _pendingDeleteForm = null;

function confirmDelete(form) {
  _pendingDeleteForm = form;
  const modal = document.getElementById('deleteModal');
  if (modal) {
    modal.classList.add('open');
    if (window.lucide) lucide.createIcons();
  }
}

function closeDeleteModal() {
  _pendingDeleteForm = null;
  const modal = document.getElementById('deleteModal');
  if (modal) modal.classList.remove('open');
}

function initDeleteModal() {
  const confirmBtn = document.getElementById('confirmDeleteBtn');
  const modal = document.getElementById('deleteModal');

  if (confirmBtn) {
    confirmBtn.addEventListener('click', () => {
      if (_pendingDeleteForm) _pendingDeleteForm.submit();
    });
  }

  if (modal) {
    modal.addEventListener('click', (e) => {
      if (e.target === modal) closeDeleteModal();
    });
  }
}

/* ── Auto-dismiss flash messages ─────────────────────────── */
function initFlashAutoDismiss() {
  setTimeout(() => {
    document.querySelectorAll('.flash-msg').forEach((el) => {
      el.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
      el.style.opacity = '0';
      el.style.transform = 'translateY(-10px)';
      setTimeout(() => el.remove(), 400);
    });
  }, 4500);
}