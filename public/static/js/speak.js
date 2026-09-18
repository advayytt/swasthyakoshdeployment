/* Read the page aloud.

   Uses the browser's own speechSynthesis via window.SwasthyaVoice (see
   voice-shared.js, which must load before this file). Voice selection,
   the Devanagari fallback chain, and the Chrome keep-alive workaround all
   live there now, shared with kiosk.js's retry-prompt. This file owns only
   what is specific to reading a whole page: splitting it into blocks,
   queuing them one after another, and pause/resume/stop controls.
*/
(function () {
  "use strict";

  var root = document.getElementById("speak-root");
  if (!root) return;

  var V = window.SwasthyaVoice;
  var btn = document.getElementById("speak-page");
  var stopBtn = document.getElementById("speak-stop");
  var note = document.getElementById("speak-note");

  if (!V || !V.isSupported()) {
    if (btn) btn.style.display = "none";
    return;
  }

  var locale = root.dataset.speechLocale || "en-IN";
  var langPrefix = locale.split("-")[0];
  var labels = {
    play: root.dataset.labelListen || "Listen to this page",
    pause: root.dataset.labelPause || "Pause",
    resume: root.dataset.labelResume || "Resume",
    stop: root.dataset.labelStop || "Stop",
    unavailable: root.dataset.labelUnavailable || "No voice available."
  };

  /* Shown when a substitute voice is used. Kept here rather than in the
     translation file so this fix is a single-file change; move it into
     data/i18n_landing.json if you prefer all copy in one place. */
  var SUBSTITUTE_NOTE = {
    mr: "मराठी आवाज उपलब्ध नाही, त्यामुळे हिंदी आवाज वापरत आहोत. उच्चार थोडे वेगळे वाटतील.",
    hi: "हिंदी आवाज़ उपलब्ध नहीं है, इसलिए मराठी आवाज़ का उपयोग कर रहे हैं। उच्चारण थोड़ा भिन्न लगेगा।",
    en: "Using a substitute voice. Pronunciation may differ."
  };

  var blocks = [];
  var index = 0;
  var state = "idle";        // idle | speaking | paused

  function showNote(text, tone) {
    if (!note) return;
    note.textContent = text;
    note.hidden = false;
    note.style.color = tone === "warn" ? "var(--haldi-deep)" : "var(--alert)";
    note.style.background = tone === "warn" ? "#FBF4E4" : "var(--alert-soft)";
  }

  /* ---------- collecting what to read ---------------------------------- */

  function collect() {
    blocks = [];
    var nodes = document.querySelectorAll("[data-speak]");
    for (var i = 0; i < nodes.length; i++) {
      var text = (nodes[i].textContent || "").replace(/\s+/g, " ").trim();
      if (text.length > 1) blocks.push({ el: nodes[i], text: text });
    }
  }

  function highlight(i) {
    for (var j = 0; j < blocks.length; j++) {
      blocks[j].el.classList.toggle("speaking", j === i);
    }
    if (i >= 0 && blocks[i]) {
      var rect = blocks[i].el.getBoundingClientRect();
      if (rect.top < 70 || rect.bottom > window.innerHeight - 40) {
        blocks[i].el.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    }
  }

  /* ---------- playback -------------------------------------------------- */

  function speakFrom(i) {
    if (i >= blocks.length) { finish(); return; }
    index = i;
    highlight(i);

    function next() {
      // Whether it succeeded or failed, move to the next block — one bad
      // block should not stop the whole page from being read.
      if (state === "speaking") speakFrom(index + 1);
    }

    if (V.bhashini) {
      V.bhashini.speak(blocks[i].text, langPrefix, function (ok) {
        if (ok) { next(); return; }
        speakBlockWithBrowserVoice(i, next);
      });
      return;
    }
    speakBlockWithBrowserVoice(i, next);
  }

  function speakBlockWithBrowserVoice(i, next) {
    V.speakOnce(blocks[i].text, locale, next, {
      interrupt: false,   // we are already mid-queue; do not cancel ourselves
      onNoVoice: function () { showNote(labels.unavailable, "error"); },
      onSubstituted: function () {
        showNote(SUBSTITUTE_NOTE[langPrefix] || SUBSTITUTE_NOTE.en, "warn");
      }
    });
  }

  function finish() {
    state = "idle";
    V.cancelAll();
    highlight(-1);
    btn.textContent = labels.play;
    btn.classList.remove("on");
    if (stopBtn) stopBtn.hidden = true;
  }

  function begin() {
    collect();
    if (!blocks.length) return;
    state = "speaking";
    btn.textContent = labels.pause;
    btn.classList.add("on");
    if (stopBtn) stopBtn.hidden = false;
    if (note) note.hidden = true;
    speakFrom(0);
  }

  /* ---------- controls -------------------------------------------------- */

  btn.addEventListener("click", function () {
    if (state === "idle") {
      begin();
    } else if (state === "speaking") {
      state = "paused";
      window.speechSynthesis.pause();
      btn.textContent = labels.resume;
    } else {
      state = "speaking";
      window.speechSynthesis.resume();
      btn.textContent = labels.pause;
    }
  });

  if (stopBtn) stopBtn.addEventListener("click", finish);

  window.addEventListener("beforeunload", function () { V.cancelAll(); });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && state !== "idle") finish();
  });
})();