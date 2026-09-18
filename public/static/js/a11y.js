/* Accessibility toolbar: text sizing.

   GIGW, the Guidelines for Indian Government Websites, expects this kind of
   control on a public-facing government service. For this product it is
   more than a compliance box: the people using the patient terminal are
   frequently elderly, and presbyopia and cataract are exactly the
   conditions that make a 15px interface unusable.

   The setting persists per browser via localStorage, and degrades silently
   if storage is unavailable (private browsing, a locked-down kiosk
   profile). The page still works, it just forgets the choice.

   Text size is applied as a --scale multiplier on :root. Every font-size in
   app.css is written as calc(Npx * var(--scale)), so one variable resizes the
   entire interface without reflowing the layout into nonsense.
*/
(function () {
  "use strict";

  var MIN = 0.85, MAX = 1.5, STEP = 0.125, DEFAULT = 1;
  var KEY_SCALE = "swasthyakosh.textScale";

  var root = document.documentElement;

  function store(key, value) {
    try { localStorage.setItem(key, value); } catch (e) { /* ignore */ }
  }

  function read(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }

  /* ---------- text size ------------------------------------------------- */

  function applyScale(value) {
    var scale = Math.min(MAX, Math.max(MIN, value));
    root.style.setProperty("--scale", String(scale));
    store(KEY_SCALE, String(scale));
    return scale;
  }

  function currentScale() {
    var raw = parseFloat(root.style.getPropertyValue("--scale"));
    return isNaN(raw) ? DEFAULT : raw;
  }

  var saved = parseFloat(read(KEY_SCALE));
  applyScale(isNaN(saved) ? DEFAULT : saved);

  var smaller = document.getElementById("text-smaller");
  var larger = document.getElementById("text-larger");
  var reset = document.getElementById("text-reset");

  if (smaller) smaller.addEventListener("click", function () {
    applyScale(currentScale() - STEP);
  });
  if (larger) larger.addEventListener("click", function () {
    applyScale(currentScale() + STEP);
  });
  if (reset) reset.addEventListener("click", function () {
    applyScale(DEFAULT);
  });
})();
