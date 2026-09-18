/* Kiosk behaviour.

   Speech recognition comes from the browser's own Web Speech API (no key,
   no cost — but note it does call out to Google's servers for recognition,
   so it needs internet even though it needs no API key). Speech synthesis
   goes through window.SwasthyaVoice (see voice-shared.js, loaded before
   this file by every kiosk screen) rather than talking to speechSynthesis
   directly, so "repeat question" and the retry prompts below get the same
   reliable voice selection the whole-page reader uses — including the
   Devanagari fallback for languages with no installed voice.

   Every voice feature degrades to tapping. If the browser has no recogniser,
   the mic hides itself and the touch options are still there. That is the
   dual-mode requirement, and it is also what keeps the demo alive when the
   venue microphone refuses to cooperate.

   RETRY PROMPT: when recognition hears nothing, errors, or hears something
   that cannot be matched to any option on screen, the app speaks a short
   prompt asking the patient to try again — in their selected language,
   through the same voice-selection path as everything else. This is the
   behaviour a non-literate patient actually needs: a failure state that is
   heard, not one that only shows as text they cannot read. It is capped at
   two automatic retries per question; after that we stop prompting and let
   the visible transcript and touch options carry it, so a patient who
   genuinely cannot get the microphone working is not stuck in a loop of the
   kiosk talking at them.
*/
(function () {
  "use strict";

  const root = document.getElementById("kiosk-root");
  if (!root) return;

  const locale = root.dataset.locale || "hi-IN";
  const form = document.getElementById("answer-form");
  const nextBtn = document.getElementById("next-btn");
  const transcriptEl = document.getElementById("transcript");
  const micBtn = document.getElementById("mic-btn");
  const micRow = document.getElementById("mic-row");
  const sourceField = document.getElementById("source-field");
  const rawField = document.getElementById("raw-field");
  const confField = document.getElementById("confidence-field");
  const textInput = document.getElementById("text-input");
  const inputType = root.dataset.inputType;

  const V = window.SwasthyaVoice;
  const voiceSupported = !!(V && V.isSupported());

  const RETRY_TEXT = {
    noSpeech: root.dataset.retryNoSpeech || "",
    notMatched: root.dataset.retryNotMatched || "",
    error: root.dataset.retryError || ""
  };
  const MAX_AUTO_RETRIES = 2;
  let retryCount = 0;

  /* ---------------- Reading the question aloud ------------------------- */

  const speakBtn = document.getElementById("speak-btn");

  function speak(text, onDone) {
    if (!text) { if (onDone) onDone(false); return; }
    var done = onDone || function () {};
    var langPrefix = locale.split(/[-_]/)[0];
    if (V && V.bhashini) {
      V.bhashini.speak(text, langPrefix, function (ok) {
        if (ok) { done(true); return; }
        if (!voiceSupported) { done(false); return; }
        V.speakOnce(text, locale, done);
      });
      return;
    }
    if (!voiceSupported) { done(false); return; }
    V.speakOnce(text, locale, done);
  }

  const promptText = root.dataset.prompt || "";
  const optionsInstruction = root.dataset.optionsInstruction || "";

  /* Reads the question, then each option with a clear pause between them,
     then the closing instruction — all as one TTS call to avoid the
     mixed-voice bug (see comment on the previous version of this function).

     Pause lengths: the question flows naturally into the first option (one
     period = brief breath), options are separated from each other by " … "
     (three dots = a longer, clearly audible pause — both Bhashini and the
     browser's own TTS treat ellipsis as a longer rest than a single period
     without needing SSML), and the last option flows naturally into the
     closing instruction again (one period). This gives the distinct gap the
     patient needs to hear where one option ends and the next begins, while
     the question and instruction don't get extra air around them. */
  function speakFullQuestion() {
    var optButtons = document.querySelectorAll(".opt");
    if (!optButtons.length) {
      // Free-text question: no options, just speak the prompt.
      speak(promptText);
      return;
    }

    var optionLabels = [];
    optButtons.forEach(function (btn) {
      var label = btn.dataset.label;
      if (label) optionLabels.push(label);
    });

    // Question → [pause] → Option 1 … Option 2 … Option N → [pause] → Instruction
    var combined = promptText +
      (optionLabels.length ? ". " + optionLabels.join(" ……………… ") : "") +
      (optionsInstruction ? ". " + optionsInstruction : "");

    speak(combined);
  }

  if (speakBtn) {
    speakBtn.addEventListener("click", speakFullQuestion);
  }
  if (root.dataset.autospeak === "1") {
    setTimeout(speakFullQuestion, 420);
  }

  /* Speak a retry prompt, then (if the recogniser exists) automatically
     reopen the microphone once the prompt finishes — so the patient does
     not have to tap the mic again after every failed attempt, only after
     MAX_AUTO_RETRIES is exhausted. */
  function speakRetryAndReopen(text) {
    if (!text) { maybeReopenMic(); return; }
    retryCount++;
    speak(text, function () {
      if (retryCount <= MAX_AUTO_RETRIES) maybeReopenMic();
    });
  }

  let reopenMicFn = null;   // set once the recogniser is constructed below
  function maybeReopenMic() {
    if (reopenMicFn) reopenMicFn();
  }

  /* ---------------- Option selection ----------------------------------- */

  const selected = new Set();

  function refreshNext() {
    if (!nextBtn) return;
    if (inputType === "text") {
      nextBtn.disabled = !(textInput && textInput.value.trim().length > 0);
    } else {
      nextBtn.disabled = selected.size === 0;
    }
  }

  document.querySelectorAll(".opt").forEach(function (btn) {
    btn.addEventListener("click", function () {
      const value = btn.dataset.value;
      // A successful tap or a successful voice match both count as answered;
      // reset the retry counter so the NEXT question starts fresh rather
      // than inheriting a near-exhausted count from this one.
      retryCount = 0;
      if (inputType === "multi") {
        if (btn.classList.contains("selected")) {
          btn.classList.remove("selected");
          selected.delete(value);
        } else {
          if (value === "none") {
            document.querySelectorAll(".opt").forEach(function (o) {
              o.classList.remove("selected");
            });
            selected.clear();
          } else {
            const noneBtn = document.querySelector('.opt[data-value="none"]');
            if (noneBtn) noneBtn.classList.remove("selected");
            selected.delete("none");
          }
          btn.classList.add("selected");
          selected.add(value);
        }
        syncHiddenMulti();
      } else {
        document.querySelectorAll(".opt").forEach(function (o) {
          o.classList.remove("selected");
        });
        btn.classList.add("selected");
        selected.clear();
        selected.add(value);
        const single = document.getElementById("value-field");
        if (single) single.value = value;
        if (sourceField && sourceField.value !== "voice") sourceField.value = "touch";
      }
      refreshNext();
    });
  });

  function syncHiddenMulti() {
    const holder = document.getElementById("multi-holder");
    if (!holder) return;
    holder.innerHTML = "";
    selected.forEach(function (v) {
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = "value";
      input.value = v;
      holder.appendChild(input);
    });
  }

  if (textInput) {
    textInput.addEventListener("input", refreshNext);
  }
  refreshNext();

  /* ---------------- Listening ------------------------------------------ */

  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;

  /* Decide the listening path once, the same way speak() decides per call:
     Bhashini first when the server has it enabled, browser SpeechRecognition
     otherwise. This used to only check Bhashini when the browser had NO
     recognizer at all — meaning a real click on Chrome/Edge, where a
     recognizer always exists, could never reach Bhashini even with valid
     credentials configured. */
  if (V && V.bhashini) {
    V.bhashini.available(function (status) {
      if (status.enabled && micBtn) {
        wireBhashiniMic();
      } else if (Recognition && micBtn) {
        wireBrowserRecognitionMic();
      } else {
        showMicUnsupported();
      }
    });
  } else if (Recognition && micBtn) {
    wireBrowserRecognitionMic();
  } else {
    showMicUnsupported();
  }

  function wireBrowserRecognitionMic() {
    const recog = new Recognition();
    recog.lang = locale;
    recog.interimResults = true;
    recog.continuous = false;
    recog.maxAlternatives = 3;

    let listening = false;
    let finalText = "";
    let bestConfidence = 0.6;
    let startRequested = false;

    function startListening() {
      if (listening || startRequested) return;
      startRequested = true;
      if (voiceSupported) V.cancelAll();
      finalText = "";
      try { recog.start(); } catch (e) { startRequested = false; }
    }

    reopenMicFn = startListening;

    micBtn.addEventListener("click", function () {
      // Stop any question/option read-aloud immediately on tap, whether or
      // not we are about to start listening — a patient tapping the mic
      // mid-narration wants the kiosk to stop talking right away, not once
      // recognition happens to kick in a moment later.
      if (voiceSupported) V.cancelAll();
      if (listening) { recog.stop(); return; }
      // A manual tap always resets the retry budget — the patient is
      // actively trying again, not being auto-retried by the app.
      retryCount = 0;
      startListening();
    });

    recog.addEventListener("start", function () {
      startRequested = false;
      listening = true;
      micBtn.classList.add("listening");
      micBtn.setAttribute("aria-label", "Stop listening");
      if (transcriptEl) {
        transcriptEl.innerHTML = "<em>" +
          (root.dataset.listeningLabel || "Listening…") + "</em>";
      }
    });

    recog.addEventListener("end", function () {
      startRequested = false;
      listening = false;
      micBtn.classList.remove("listening");
      micBtn.setAttribute("aria-label", "Speak your answer");
      if (finalText) {
        applyTranscript(finalText, bestConfidence);
      }
      // If recog ended with no finalText and no error event fired (some
      // browsers end silently rather than emitting "no-speech"), treat it
      // as the no-speech case so the patient still gets a spoken prompt
      // rather than the mic just going quiet with no explanation.
      else if (retryCount < MAX_AUTO_RETRIES + 1) {
        handleFailure("noSpeech");
      }
    });

    /* Say which of the four failures actually happened, in TEXT (for anyone
       who can read this screen) — this part is unchanged from before.
       What is new is handleFailure() below, which ALSO speaks a short
       prompt aloud, because the whole point of this screen is that the
       person in front of it may not be able to read the text this sets. */
    var SPEECH_ERRORS = {
      "no-speech":
        "Did not hear anything. Tap the microphone and start speaking straight away.",
      "audio-capture":
        "No microphone found. Check it is connected and not muted.",
      "not-allowed":
        "Microphone permission was refused. Allow it from the padlock icon in the address bar, or tap an option below.",
      "service-not-allowed":
        "This browser does not allow speech recognition. Brave blocks it by default \u2014 open this page in Chrome or Edge. Every question can still be answered by tapping.",
      "network":
        "Speech recognition needs an internet connection, even though it needs no API key. Check the network, or tap an option below.",
      "aborted":
        "Listening stopped. Tap the microphone to try again."
    };

    // Errors that a spoken retry prompt can actually help with. The others
    // (not-allowed, service-not-allowed, audio-capture) are configuration
    // problems no amount of "please speak again" will fix, and for
    // service-not-allowed specifically we cannot even speak the prompt
    // reliably if the browser is this restrictive — show text only.
    var RETRYABLE_ERRORS = { "no-speech": true, "network": true, "aborted": true };

    recog.addEventListener("error", function (e) {
      startRequested = false;
      listening = false;
      micBtn.classList.remove("listening");
      if (transcriptEl) {
        transcriptEl.textContent =
          SPEECH_ERRORS[e.error] ||
          ("Speech input failed (" + e.error + "). Tap an option below.");
      }
      if (RETRYABLE_ERRORS[e.error] && retryCount < MAX_AUTO_RETRIES) {
        handleFailure(e.error === "no-speech" ? "noSpeech" : "error");
      }
    });

    recog.addEventListener("result", function (event) {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const res = event.results[i];
        if (res.isFinal) {
          finalText += res[0].transcript;
          if (res[0].confidence) bestConfidence = res[0].confidence;
        } else {
          interim += res[0].transcript;
        }
      }
      if (transcriptEl) {
        transcriptEl.textContent = finalText + interim;
      }
    });
  }

  /* ---------------- Bhashini-backed mic (primary when enabled) ---------- */

  var BHASHINI_MIC_ERRORS = {
    microphone_denied: "Microphone permission was refused. Allow it from the padlock icon in the address bar, or tap an option below.",
    no_microphone_api: "This browser cannot access the microphone. Tap an option below.",
    network_unreachable: "Could not reach the server. Check the network, or tap an option below.",
    bhashini_disabled: "Speech service is off on the server. Tap an option below.",
    no_audio_provided: "No audio was recorded. Tap the microphone and try again.",
    config_unavailable: "Voice service is not available right now. Tap an option below.",
    unparsable_response: "Got an unexpected reply from the speech service. Tap an option below.",
    transcribe_failed: "Could not reach the speech service. Check the network, or tap an option below."
  };

  function bhashiniMicErrorText(code) {
    if (code && code.indexOf("no_asr_service_for_language:") === 0) {
      return "Speech recognition isn't available for this language yet. Tap an option below.";
    }
    return BHASHINI_MIC_ERRORS[code] ||
      "Could not hear that. Tap an option below, or tap the microphone to try again.";
  }

  function wireBhashiniMic() {
    var recording = false;
    var stopFn = null;
    var langPrefix = locale.split(/[-_]/)[0];

    reopenMicFn = function () { if (!recording) micBtn.click(); };

    micBtn.addEventListener("click", function () {
      // Stop any question/option read-aloud immediately on tap — see the
      // matching comment in wireBrowserRecognitionMic() above.
      if (voiceSupported) V.cancelAll();
      if (recording) { if (stopFn) stopFn(); return; }
      retryCount = 0;
      recording = true;
      stopFn = null;
      micBtn.classList.add("listening");
      micBtn.setAttribute("aria-label", "Stop listening");
      if (transcriptEl) {
        transcriptEl.innerHTML = "<em>" +
          (root.dataset.listeningLabel || "Listening…") + "</em>";
      }

      V.bhashini.recordAndTranscribe(
        langPrefix,
        15000,
        function (stop) { stopFn = stop; },
        function (result) {
          recording = false;
          micBtn.classList.remove("listening");
          micBtn.setAttribute("aria-label", "Speak your answer");
          if (!result.ok) {
            if (transcriptEl) {
              transcriptEl.textContent = bhashiniMicErrorText(result.error);
            }
            if (retryCount < MAX_AUTO_RETRIES) handleFailure("error");
            return;
          }
          if (!result.text) {
            if (transcriptEl) {
              transcriptEl.textContent =
                "Did not catch that. Tap the microphone and try again, or tap an option below.";
            }
            if (retryCount < MAX_AUTO_RETRIES) handleFailure("noSpeech");
            return;
          }
          applyTranscript(result.text, result.confidence || 0.7);
        }
      );
    });
  }

  function showMicUnsupported() {
    if (micRow) {
      micRow.innerHTML =
        '<div class="mic-hint">Voice input is not available in this browser. ' +
        'Chrome and Edge support it; Brave, Firefox and Safari do not. ' +
        'Every question here can still be answered by tapping.</div>';
    }
  }

  /* ---------------- Speaking the retry prompt --------------------------- */

  function handleFailure(kind) {
    if (retryCount >= MAX_AUTO_RETRIES) return;   // budget spent, stay quiet
    const text = kind === "noSpeech" ? RETRY_TEXT.noSpeech
               : kind === "notMatched" ? RETRY_TEXT.notMatched
               : RETRY_TEXT.error;
    speakRetryAndReopen(text);
  }

  /* ---------------- Matching speech to an option ------------------------ */

  function normalise(s) {
    return (s || "").toLowerCase().replace(/[^\p{L}\p{N} ]/gu, " ")
      .replace(/\s+/g, " ").trim();
  }

  function applyTranscript(text, confidence) {
    if (sourceField) sourceField.value = "voice";
    if (rawField) rawField.value = text;
    if (confField) confField.value = String(Math.max(0.35, Math.min(confidence || 0.6, 0.97)));

    if (transcriptEl) transcriptEl.textContent = text;

    if (inputType === "text") {
      if (textInput) {
        textInput.value = textInput.value ? textInput.value + " " + text : text;
      }
      retryCount = 0;   // free text has no "not matched" failure mode
      refreshNext();
      return;
    }

    /* Match the spoken words against the visible option labels. Anything we
       cannot match confidently is left for the patient to tap — we never
       guess a clinical answer on the patient's behalf. */
    const spoken = normalise(text);
    let hit = null;
    let hitScore = 0;

    document.querySelectorAll(".opt").forEach(function (btn) {
      const labels = [btn.dataset.label, btn.dataset.labelEn, btn.dataset.value];
      labels.forEach(function (label) {
        const target = normalise(label);
        if (!target || target.length < 2) return;
        let score = 0;
        if (spoken.includes(target)) {
          score = target.length;
        } else {
          const words = target.split(" ").filter(function (w) { return w.length > 2; });
          const matched = words.filter(function (w) { return spoken.includes(w); });
          if (words.length && matched.length / words.length >= 0.5) {
            score = matched.join("").length;
          }
        }
        if (score > hitScore) { hitScore = score; hit = btn; }
      });
    });

    if (hit && hitScore >= 3) {
      hit.click();  // this resets retryCount, see the click handler above
      if (sourceField) sourceField.value = "voice";
      if (transcriptEl) {
        transcriptEl.innerHTML =
          text + ' <em>→ ' + (hit.dataset.label || "") + "</em>";
      }
    } else {
      if (transcriptEl) {
        transcriptEl.innerHTML =
          text + ' <em>— not matched, please tap your answer</em>';
      }
      if (retryCount < MAX_AUTO_RETRIES) handleFailure("notMatched");
    }
  }

  /* ---------------- Guard against double submits ------------------------ */

  if (form) {
    form.addEventListener("submit", function () {
      if (nextBtn) {
        nextBtn.disabled = true;
        nextBtn.textContent = "Saving…";
      }
      if (voiceSupported) V.cancelAll();
    });
  }
})();
