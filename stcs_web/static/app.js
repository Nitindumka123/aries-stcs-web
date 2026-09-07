/* ARIES STCS live telemetry refresh (no framework).
   Pages render server-side instantly; this script then polls the read-only
   /api/telemetry/snapshot endpoint and updates [data-live] nodes in place,
   so the console stays current without full-page reloads. On any failure
   it leaves the last server-rendered values untouched. */
(function () {
  "use strict";
  function tickClock() {
    var el = document.getElementById("clock");
    if (el) el.textContent = new Date().toLocaleTimeString("en-GB");
  }
  tickClock(); setInterval(tickClock, 1000);

  var nodes = document.querySelectorAll("[data-live]");
  if (!nodes.length) return;

  function pad(n, l) { n = String(n); while (n.length < (l || 2)) n = "0" + n; return n; }
  function fmtHMS(h) {
    if (h === null || h === undefined || isNaN(h)) return "—";
    h = ((h % 24) + 24) % 24;
    var H = Math.floor(h), M = Math.floor((h - H) * 60);
    var S = ((h - H - M / 60) * 3600).toFixed(h === Math.floor(h) && M === 0 ? 2 : 1);
    return pad(H) + ":" + pad(M) + ":" + (S < 10 ? "0" + S : S);
  }
  function fmtDMS(d) {
    if (d === null || d === undefined || isNaN(d)) return "—";
    var s = d >= 0 ? "+" : "−", a = Math.abs(d);
    var D = Math.floor(a), M = Math.floor((a - D) * 60);
    var S = ((a - D - M / 60) * 3600).toFixed(1);
    return s + pad(D) + "°" + pad(M) + "′" + (S < 10 ? "0" + S : S) + "″";
  }
  function fmtDeg(v, digits) {
    if (v === null || v === undefined || isNaN(v)) return "—";
    return (v >= 0 ? "+" : "") + v.toFixed(digits === undefined ? 2 : digits) + "°";
  }
  function word(st) {
    return { LIVE: "Live", STALE: "Stale", NOT_CONNECTED: "Disconnected",
             NOT_AVAILABLE: "Not available", UNKNOWN: "Unknown" }[st] || st || "—";
  }
  function setText(sel, txt) {
    document.querySelectorAll(sel).forEach(function (el) { el.textContent = txt; });
  }

  var lastOk = 0;
  function poll() {
    fetch("/api/telemetry/snapshot", { credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error("http " + r.status); return r.json(); })
      .then(function (s) {
        lastOk = Date.now();
        var lst = s.lst_hours, ra = s.ra_hours;
        var hra = (lst !== null && ra !== null && lst !== undefined && ra !== undefined)
          ? ((lst - ra) % 24 + 24) % 24 : null;
        var map = {
          ra: fmtHMS(ra), dec: fmtDMS(s.dec_deg), hra: fmtHMS(hra),
          az: fmtDeg(s.az_deg), alt: fmtDeg(s.alt_deg),
          lst: fmtHMS(lst) + (s.lst_source && s.lst_source !== "ALPACA" ? " *" : ""),
          tracking: s.tracking === true ? "ON" : (s.tracking === false ? "OFF" : "UNKNOWN"),
          motion: s.slewing === true ? "SLEWING" : (s.slewing === false ? "IDLE" : "UNKNOWN"),
          alpaca: word(s.alpaca_status),
          safety: (s.safety && s.safety.overall) || "UNKNOWN"
        };
        Object.keys(map).forEach(function (k) { setText('[data-live="' + k + '"]', map[k]); });
        var w = (s.weather && s.weather.values) || {};
        setText('[data-live="temp"]', w.temp_c !== null && w.temp_c !== undefined ? w.temp_c + " °C" : "—");
        setText('[data-live="hum"]', w.humidity_pct !== null && w.humidity_pct !== undefined ? w.humidity_pct + " %" : "—");
      })
      .catch(function () { /* keep last rendered values */ });
  }
  tickClock(); setInterval(tickClock, 1000);
  poll(); setInterval(poll, 3000);

  // sub-tab switching (secondary pages only; CONTROL has no sub-tabs)
  document.querySelectorAll("[data-subtab]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var bar = btn.parentElement;
      bar.querySelectorAll("button").forEach(function (b) { b.classList.remove("on"); });
      btn.classList.add("on");
      var scope = btn.closest(".ws") || document;
      scope.querySelectorAll("[data-pane]").forEach(function (p) {
        p.style.display = (p.getAttribute("data-pane") === btn.getAttribute("data-subtab")) ? "" : "none";
      });
    });
  });
})();
