/* Per-field voice dictation for multi-field kiosk forms (register, identify,
   verify, requests) where kiosk.js's single-question-per-screen model does
   not apply — there is no single "answer-form" or one option grid to match
   speech against, just several ordinary fields on one screen.

   Markup contract: a button with class "field-mic" and data-target="<input
   id>" placed next to any field that should accept dictation.

   Path choice matches kiosk.js and speak.js: Bhashini first when the server
   has it enabled (via window.SwasthyaVoice.bhashini, see voice-shared.js),
   the browser's own SpeechRecognition otherwise. Earlier this used browser
   recognition whenever it existed and only reached Bhashini when it didn't
   — backwards from the intended design, and meant a real click in Chrome
   never used Bhashini even with valid credentials configured.

   Every button also gets a small status note inserted right after it
   ("Listening…", "Could not hear that", "Microphone permission was
   refused…"). A mic that does nothing visible on failure is indistinguishable
   from a mic that is simply broken — this makes every outcome visible,
   not just the successful one.

   Load after voice-shared.js. Safe to include on any page — it does nothing
   if no ".field-mic" buttons are present.
*/
(function () {
  "use strict";

  var buttons = document.querySelectorAll(".field-mic");
  if (!buttons.length) return;

  var V = window.SwasthyaVoice;
  var root = document.getElementById("kiosk-root");
  var pageLocale = (root && root.dataset.locale) || "hi-IN";

  var Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;

  var BROWSER_ERRORS = {
    "no-speech": "Did not hear anything. Tap and speak straight away.",
    "audio-capture": "No microphone found. Check it is connected and not muted.",
    "not-allowed": "Microphone permission was refused. Allow it from the padlock icon in the address bar.",
    "service-not-allowed": "This browser blocks speech recognition. Try Chrome or Edge, or type instead.",
    "network": "Needs an internet connection. Check the network, or type instead.",
    "aborted": "Listening stopped. Tap the microphone to try again."
  };
  var BHASHINI_ERRORS = {
    microphone_denied: "Microphone permission was refused. Allow it from the padlock icon in the address bar.",
    no_microphone_api: "This browser cannot access the microphone here.",
    network_unreachable: "Could not reach the server. Check the network.",
    bhashini_disabled: "Speech service is off on the server.",
    no_audio_provided: "No audio was recorded. Try again.",
    config_unavailable: "Voice service is not available right now.",
    unparsable_response: "Got an unexpected reply from the speech service.",
    transcribe_failed: "Could not reach the speech service. Check the network."
  };
  function bhashiniFieldErrorText(code) {
    if (code && code.indexOf("no_asr_service_for_language:") === 0) {
      return "Speech recognition isn't available for this language yet.";
    }
    return BHASHINI_ERRORS[code] || "Could not hear that. Try again, or type instead.";
  }

  function applyText(field, text) {
    if (!text) return;
    if (field.tagName === "SELECT") {
      var spoken = text.toLowerCase().trim();
      var opts = Array.prototype.slice.call(field.options);
      var hit = opts.filter(function (o) {
        var label = o.textContent.toLowerCase();
        return label.indexOf(spoken) !== -1 || spoken.indexOf(label) !== -1;
      })[0];
      if (hit) field.value = hit.value;
    } else if (field.type === "number" || field.inputMode === "numeric" ||
               field.type === "tel") {
      var digits = text.replace(/[^\d]/g, "");
      if (digits) field.value = digits;
    } else {
      field.value = field.value ? field.value + " " + text : text;
    }
    field.dispatchEvent(new Event("input", { bubbles: true }));
    field.focus();
  }

  function makeNote(btn) {
    var note = document.createElement("span");
    note.className = "field-mic-note";
    btn.insertAdjacentElement("afterend", note);
    return note;
  }

  buttons.forEach(function (btn) {
    var field = document.getElementById(btn.dataset.target);
    if (!field) { btn.disabled = true; return; }

    var locale = btn.dataset.locale || pageLocale;
    var langPrefix = locale.split(/[-_]/)[0];
    var note = makeNote(btn);
    var listening = false;

    function setListening(on) {
      listening = on;
      btn.classList.toggle("listening", on);
    }
    function showNote(text) { note.textContent = text || ""; }

    function wireBrowserRecognition() {
      var recog = new Recognition();
      recog.lang = locale;
      recog.interimResults = false;
      recog.continuous = false;
      recog.maxAlternatives = 1;

      recog.addEventListener("start", function () {
        setListening(true);
        showNote("Listening…");
      });
      recog.addEventListener("end", function () { setListening(false); });
      recog.addEventListener("error", function (e) {
        setListening(false);
        showNote(BROWSER_ERRORS[e.error] ||
          ("Speech input failed (" + e.error + ")."));
      });
      recog.addEventListener("result", function (e) {
        var res = e.results[0] && e.results[0][0];
        if (res && res.transcript) {
          applyText(field, res.transcript);
          showNote("");
        } else {
          showNote("Did not catch that. Try again, or type instead.");
        }
      });

      btn.addEventListener("click", function () {
        if (V && V.cancelAll) V.cancelAll();
        if (listening) { recog.stop(); return; }
        showNote("");
        try { recog.start(); } catch (e) { /* already starting, ignore */ }
      });
    }

    function wireBhashini() {
      var stopFn = null;
      btn.addEventListener("click", function () {
        if (V && V.cancelAll) V.cancelAll();
        if (listening) { if (stopFn) stopFn(); return; }
        setListening(true);
        showNote("Listening…");
        V.bhashini.recordAndTranscribe(
          langPrefix,
          5000,
          function (stop) { stopFn = stop; },
          function (result) {
            setListening(false);
            stopFn = null;
            if (!result.ok) {
              showNote(bhashiniFieldErrorText(result.error));
              return;
            }
            if (!result.text) {
              showNote("Did not catch that. Try again, or type instead.");
              return;
            }
            applyText(field, result.text);
            showNote("");
          }
        );
      });
    }

    if (V && V.bhashini) {
      V.bhashini.available(function (status) {
        if (status.enabled) { wireBhashini(); return; }
        if (Recognition) { wireBrowserRecognition(); return; }
        btn.disabled = true;
        showNote("Voice input is not available in this browser.");
      });
      return;
    }

    if (Recognition) { wireBrowserRecognition(); return; }
    btn.disabled = true;
    showNote("Voice input is not available in this browser.");
  });
})();
