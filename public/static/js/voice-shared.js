/* Shared speech-synthesis core.

   Extracted from speak.js so the same robust voice-picking logic (exact
   locale match -> same language, any region -> related-script fallback ->
   give up honestly) is available to any script that needs to say ONE short
   thing out loud, not just the whole-page reader. kiosk.js uses this for the
   "please speak again" retry prompt; speak.js uses it for reading page
   content, wrapping it with its own block-queue and pause/resume machinery.

   Nothing in here talks to a server. No API key. This is what runs today,
   on every screen, regardless of whether Bhashini is ever enabled.

   Load this script BEFORE speak.js and kiosk.js on any page that uses either.
*/
window.SwasthyaVoice = (function () {
  "use strict";

  var synth = window.speechSynthesis;
  var supported = !!(synth && window.SpeechSynthesisUtterance);

  /* When the exact language has no installed voice, try these in order.
     Devanagari languages can read each other's text passably; English
     cannot read either usefully, so it is never offered as a fallback FOR
     Hindi or Marathi, only as itself. */
  var FALLBACK_CHAIN = {
    mr: ["hi", "sa", "ne"],
    hi: ["mr", "sa", "ne"],
    en: []
  };

  function voicesFor(prefix) {
    var voices = synth.getVoices() || [];
    return voices.filter(function (v) {
      return (v.lang || "").split(/[-_]/)[0].toLowerCase() === prefix;
    });
  }

  /* Returns {voice, substituted} | {voice: null, substituted: false} | undefined.
     undefined means "voices have not loaded yet, ask again after
     voiceschanged fires" — callers must handle this, not treat it as
     failure. */
  function pickVoice(locale) {
    var voices = synth.getVoices() || [];
    if (!voices.length) return undefined;

    var langPrefix = locale.split(/[-_]/)[0].toLowerCase();

    var exact = voices.filter(function (v) {
      return (v.lang || "").replace("_", "-") === locale;
    });
    if (exact.length) return { voice: exact[0], substituted: false };

    var loose = voicesFor(langPrefix);
    if (loose.length) return { voice: loose[0], substituted: false };

    var chain = FALLBACK_CHAIN[langPrefix] || [];
    for (var i = 0; i < chain.length; i++) {
      var alt = voicesFor(chain[i]);
      if (alt.length) return { voice: alt[0], substituted: true };
    }

    return { voice: null, substituted: false };
  }

  /* Same "voices not loaded yet" dance every caller needs, done once here
     rather than copy-pasted into every script that speaks. */
  function readyVoice(locale, callback) {
    var result = pickVoice(locale);
    if (result !== undefined) { callback(result); return; }
    var done = false;
    function handler() {
      if (done) return;
      done = true;
      synth.removeEventListener("voiceschanged", handler);
      callback(pickVoice(locale) || { voice: null, substituted: false });
    }
    synth.addEventListener("voiceschanged", handler);
    setTimeout(handler, 1500);
  }

  /**
   * Speak one short piece of text once, then call done().
   *
   * options:
   *   locale        e.g. "hi-IN" (required)
   *   rate          default 0.92, or 0.86 automatically when substituting
   *   interrupt     if true (default), cancels anything currently speaking
   *                 first. Pass false to queue behind existing speech.
   *   onNoVoice     called instead of speaking if no usable voice exists at
   *                 all (not even a fallback) — e.g. a completely unsupported
   *                 language on a bare-bones browser build.
   *   onSubstituted called (once, before speaking) if a related-language
   *                 voice is being used instead of the exact one asked for.
   *
   * Returns true if speech was scheduled (even if it later fails silently
   * for reasons outside our control), false if speech synthesis is not
   * supported in this browser at all.
   */
  function speakOnce(text, locale, done, options) {
    options = options || {};
    if (!supported || !text) {
      if (done) done(false);
      return false;
    }

    readyVoice(locale, function (result) {
      if (!result.voice) {
        if (options.onNoVoice) options.onNoVoice();
        if (done) done(false);
        return;
      }
      if (result.substituted && options.onSubstituted) {
        options.onSubstituted();
      }

      if (options.interrupt !== false) synth.cancel();

      var utter = new SpeechSynthesisUtterance(text);
      utter.voice = result.voice;
      utter.lang = result.voice.lang;
      utter.rate = options.rate || (result.substituted ? 0.86 : 0.95);
      utter.pitch = 1;

      var finished = false;
      function finish(ok) {
        if (finished) return;
        finished = true;
        if (done) done(ok);
      }
      utter.onend = function () { finish(true); };
      utter.onerror = function () { finish(false); };

      synth.speak(utter);

      // Chrome silently drops long-running synthesis after ~15s with no
      // pause/resume heartbeat. A single retry prompt is a sentence and
      // finishes long before that, but guard anyway in case a caller passes
      // something longer than intended.
      var heartbeat = setInterval(function () {
        if (finished || !synth.speaking) { clearInterval(heartbeat); return; }
        synth.pause();
        synth.resume();
      }, 10000);
    });

    return true;
  }

  function isSupported() { return supported; }
  var currentBhashiniAudio = null;
  function cancelAll() {
    if (synth) synth.cancel();
    // Also stop a Bhashini TTS clip in flight, if any -- synth.cancel()
    // only touches the browser's own speechSynthesis and has no idea this
    // <audio> element exists. Without this, tapping the mic mid-narration
    // while Bhashini is the active TTS path (see bhashiniSpeak() below)
    // silenced nothing and the question kept reading itself out loud.
    if (currentBhashiniAudio) {
      try {
        currentBhashiniAudio.pause();
        currentBhashiniAudio.currentTime = 0;
      } catch (e) { /* ignore */ }
      currentBhashiniAudio = null;
    }
  }

  /* ----------------------------------------------------------------------
     Bhashini bridge (optional, server-mediated).

     Everything above this point runs with zero network calls and zero
     server involvement -- it is what the kiosk has run on since day one.
     This section is additive: when BHASHINI_ENABLED=true on the server,
     these functions give callers (kiosk.js, speak.js, field-voice.js) a way
     to route through Bhashini's Indian-language models instead of the
     browser's own recognizer/synthesizer, with a done(ok) contract that
     matches speakOnce() above -- a caller tries one, then falls back to the
     other, without branching logic duplicated in three files.

     status() is fetched once and cached for the page's lifetime. A kiosk
     session is one patient, one visit; the flag will not change mid-session,
     and re-checking it before every question would just be latency with no
     benefit.
  ---------------------------------------------------------------------- */
  var bhashiniStatus = null;
  var bhashiniStatusPromise = null;

  function bhashiniAvailable(callback) {
    if (bhashiniStatus) { callback(bhashiniStatus); return; }
    if (!bhashiniStatusPromise) {
      bhashiniStatusPromise = fetch("/speech/status")
        .then(function (r) { return r.ok ? r.json() : { enabled: false }; })
        .catch(function () { return { enabled: false }; })
        .then(function (data) {
          bhashiniStatus = { enabled: !!data.enabled, label: data.label || "" };
          return bhashiniStatus;
        });
    }
    bhashiniStatusPromise.then(callback);
  }

  /* Text to speech via Bhashini. Same done(ok) contract as speakOnce() so a
     caller can do: bhashiniSpeak(text, lang, function(ok){ if(!ok)
     speakOnce(text, lang, done); }). Never falls back internally -- only the
     caller knows whether its context prefers a fallback or silence (the
     retry prompt, for one, would rather stay quiet than wait on a slow
     network call). */
  function bhashiniSpeak(text, lang, done, options) {
    options = options || {};
    if (!text) { done(false); return; }
    bhashiniAvailable(function (status) {
      if (!status.enabled) { done(false); return; }
      fetch("/speech/synthesize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: text, lang: lang, gender: options.gender || "female" })
      })
        .then(function (r) { return r.ok ? r.json() : Promise.reject(new Error("bad_status")); })
        .then(function (data) {
          if (!data.audio_base64) { done(false); return; }
          var audio = new Audio("data:audio/wav;base64," + data.audio_base64);
          currentBhashiniAudio = audio;
          var finished = false;
          function finish(ok) {
            if (finished) return;
            finished = true;
            if (currentBhashiniAudio === audio) currentBhashiniAudio = null;
            done(ok);
          }
          audio.onended = function () { finish(true); };
          audio.onerror = function () { finish(false); };
          audio.play().catch(function () { finish(false); });
        })
        .catch(function () { done(false); });
    });
  }

  /* Record a short utterance as 16-bit mono PCM WAV at 16kHz -- the exact
     shape services/bhashini.py's transcribe() expects (audio_format="wav",
     sampling_rate=16000) -- then POST it to /speech/transcribe.

     This exists for browsers with no SpeechRecognition at all (Brave,
     Firefox, Safari): today those show "voice input is not available" and
     fall back to tapping only. When Bhashini is enabled, this gives them a
     real spoken-answer path using nothing but getUserMedia + Web Audio,
     both far more widely supported than SpeechRecognition. It does NOT
     replace SpeechRecognition where that already works -- the interim
     results and tap-to-stop experience there is better than a fixed-length
     record-then-send round trip.

     onStart(stop) fires once recording actually begins, handing back a
     stop() function the caller can invoke early (e.g. the patient taps the
     mic again to finish speaking); recording also auto-stops after maxMs.
     onResult({ok, text, confidence} | {ok:false, error}) fires exactly once. */
  function recordAndTranscribe(lang, maxMs, onStart, onResult) {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      onResult({ ok: false, error: "no_microphone_api" });
      return;
    }
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
      var AudioCtx = window.AudioContext || window.webkitAudioContext;
      var ctx = new AudioCtx();
      var source = ctx.createMediaStreamSource(stream);
      var processor = ctx.createScriptProcessor(4096, 1, 1);
      var chunks = [];
      var inputRate = ctx.sampleRate;
      var stopped = false;

      source.connect(processor);
      processor.connect(ctx.destination);
      processor.onaudioprocess = function (e) {
        chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
      };

      function stop() {
        if (stopped) return;
        stopped = true;
        clearTimeout(timer);
        processor.disconnect();
        source.disconnect();
        stream.getTracks().forEach(function (t) { t.stop(); });
        ctx.close();

        var wavBlob = encodeWav(chunks, inputRate, 16000);
        var form = new FormData();
        form.append("audio", wavBlob, "utterance.wav");
        form.append("lang", lang);
        form.append("format", "wav");
        form.append("sample_rate", "16000");

        fetch("/speech/transcribe", { method: "POST", body: form })
          .then(function (r) {
            return r.json().then(function (data) {
              return { httpOk: r.ok, data: data };
            }).catch(function () {
              // Response wasn't JSON at all (proxy error page, etc.) -- no
              // server-supplied reason to surface, fall through to generic.
              return { httpOk: r.ok, data: {} };
            });
          })
          .then(function (parsed) {
            if (!parsed.httpOk) {
              onResult({ ok: false, error: parsed.data.error || "transcribe_failed" });
              return;
            }
            onResult({ ok: true, text: parsed.data.text, confidence: parsed.data.confidence });
          })
          .catch(function () {
            // fetch() itself rejected -- this IS a real network/DNS failure,
            // never reached the server at all.
            onResult({ ok: false, error: "network_unreachable" });
          });
      }

      var timer = setTimeout(stop, maxMs || 6000);
      if (onStart) onStart(stop);
    }).catch(function () {
      onResult({ ok: false, error: "microphone_denied" });
    });
  }

  /* Nearest-neighbour downsample of merged float32 PCM to 16-bit
     little-endian mono WAV at targetRate. Good enough for speech
     recognition input; not intended for higher-fidelity uses. */
  function encodeWav(chunks, sourceRate, targetRate) {
    var length = chunks.reduce(function (n, c) { return n + c.length; }, 0);
    var merged = new Float32Array(length);
    var offset = 0;
    chunks.forEach(function (c) { merged.set(c, offset); offset += c.length; });

    var ratio = sourceRate / targetRate;
    var outLength = Math.max(1, Math.floor(merged.length / ratio));
    var resampled = new Float32Array(outLength);
    for (var i = 0; i < outLength; i++) {
      resampled[i] = merged[Math.floor(i * ratio)] || 0;
    }

    var buffer = new ArrayBuffer(44 + resampled.length * 2);
    var view = new DataView(buffer);
    function writeString(off, s) {
      for (var j = 0; j < s.length; j++) view.setUint8(off + j, s.charCodeAt(j));
    }
    writeString(0, "RIFF");
    view.setUint32(4, 36 + resampled.length * 2, true);
    writeString(8, "WAVE");
    writeString(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, targetRate, true);
    view.setUint32(28, targetRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeString(36, "data");
    view.setUint32(40, resampled.length * 2, true);
    var pos = 44;
    for (var k = 0; k < resampled.length; k++, pos += 2) {
      var s = Math.max(-1, Math.min(1, resampled[k]));
      view.setInt16(pos, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
    return new Blob([view], { type: "audio/wav" });
  }

  return {
    speakOnce: speakOnce,
    pickVoice: pickVoice,
    readyVoice: readyVoice,
    isSupported: isSupported,
    cancelAll: cancelAll,
    bhashini: {
      available: bhashiniAvailable,
      speak: bhashiniSpeak,
      recordAndTranscribe: recordAndTranscribe
    }
  };
})();