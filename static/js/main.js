// Close a <dialog> when clicking directly on its backdrop.
// Native <dialog> click events target the dialog element itself when the
// click lands on the ::backdrop (outside the rendered content box), so we
// only need to check e.target === dlg — no coordinate math needed, and it
// never fires for the button that opened the dialog.
document.querySelectorAll("dialog.modal").forEach(function (dlg) {
  dlg.addEventListener("click", function (e) {
    if (e.target === dlg) dlg.close();
  });
});
