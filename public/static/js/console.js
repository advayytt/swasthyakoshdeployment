/* Clinician console behaviour: terminology search with dual-code preview. */
(function () {
  "use strict";

  const box = document.getElementById("term-search");
  const results = document.getElementById("term-results");
  const hidden = document.getElementById("namaste_code");
  const chosen = document.getElementById("chosen-code");
  if (!box || !results) return;

  let timer = null;

  function render(items) {
    results.innerHTML = "";
    if (!items.length) {
      results.innerHTML =
        '<p class="empty" style="padding:16px">No term matches that. ' +
        'Try the biomedical name, or a symptom word.</p>';
      return;
    }
    items.forEach(function (item) {
      const el = document.createElement("div");
      el.className = "code-pick";
      el.tabIndex = 0;
      el.innerHTML =
        '<div class="term">' + item.term +
        ' <span class="tag">' + item.system + "</span></div>" +
        '<div class="maps"><b>NAMASTE</b> ' + item.code +
        "  ·  <b>TM2</b> " + (item.icd11_tm2_code || "—") +
        "  ·  <b>MMS</b> " + (item.icd11_biomed_code || "—") +
        (item.icd11_biomed_term ? " (" + item.icd11_biomed_term + ")" : "") +
        "</div>";

      function pick() {
        document.querySelectorAll(".code-pick").forEach(function (n) {
          n.classList.remove("on");
        });
        el.classList.add("on");
        if (hidden) hidden.value = item.code;
        if (chosen) {
          chosen.innerHTML =
            '<div class="dual-chip"><small>NAMASTE</small><b>' + item.code +
            "</b></div>" +
            '<div class="dual-chip"><small>ICD-11 TM2</small><b>' +
            (item.icd11_tm2_code || "—") + "</b></div>" +
            '<div class="dual-chip"><small>ICD-11 Biomedicine</small><b>' +
            (item.icd11_biomed_code || "—") + "</b></div>";
        }
      }

      el.addEventListener("click", pick);
      el.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); }
      });
      results.appendChild(el);
    });
  }

  function search() {
    const q = box.value.trim();
    const complaint = box.dataset.complaint || "";
    fetch("/clinician/api/terminology?q=" + encodeURIComponent(q) +
          "&complaint=" + encodeURIComponent(complaint))
      .then(function (r) { return r.json(); })
      .then(render)
      .catch(function () {
        results.innerHTML =
          '<p class="empty" style="padding:16px">Terminology service did not ' +
          "respond. The seeded codes are still selectable from the suggestions " +
          "above.</p>";
      });
  }

  box.addEventListener("input", function () {
    clearTimeout(timer);
    timer = setTimeout(search, 220);
  });

  /* Pre-fill with complaint-ranked suggestions on load. */
  search();
})();
