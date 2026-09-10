/* ARIES STCS -- Telemetry live refresh + shared utilities.
   Server renders all pages instantly; this script polls the read-only
   /api/telemetry/snapshot endpoint and updates [data-live] nodes.
   On failure it leaves last server-rendered values untouched. */
(function () {
  "use strict";

  /* -- Clock ------------------------------------------------ */
  function tickClock() {
    var el = document.getElementById("clock");
    if (el) el.textContent = new Date().toLocaleTimeString("en-GB");
  }
  tickClock();
  setInterval(tickClock, 1000);

  /* -- Telemetry poll --------------------------------------- */
  var nodes = document.querySelectorAll("[data-live]");
  if (!nodes.length) return;

  function pad(n, l) {
    n = String(n);
    while (n.length < (l || 2)) n = "0" + n;
    return n;
  }
  function fmtHMS(h) {
    if (h === null || h === undefined || isNaN(h)) return "\u2014";
    h = ((h % 24) + 24) % 24;
    var H = Math.floor(h);
    var M = Math.floor((h - H) * 60);
    var S = ((h - H - M / 60) * 3600).toFixed(h === Math.floor(h) && M === 0 ? 2 : 1);
    return pad(H) + ":" + pad(M) + ":" + (S < 10 ? "0" + S : S);
  }
  function fmtDMS(d) {
    if (d === null || d === undefined || isNaN(d)) return "\u2014";
    var s = d >= 0 ? "+" : "\u2212";
    var a = Math.abs(d);
    var D = Math.floor(a);
    var M = Math.floor((a - D) * 60);
    var S = ((a - D - M / 60) * 3600).toFixed(1);
    return s + pad(D) + "\u00b0" + pad(M) + "\u2032" + (S < 10 ? "0" + S : S) + "\u2033";
  }
  function fmtDeg(v) {
    if (v === null || v === undefined || isNaN(v)) return "\u2014";
    return (v >= 0 ? "+" : "") + v.toFixed(2) + "\u00b0";
  }
  function setText(sel, txt) {
    document.querySelectorAll(sel).forEach(function (el) {
      el.textContent = txt;
    });
  }
  function setClass(sel, cls) {
    document.querySelectorAll(sel).forEach(function (el) {
      el.className = el.className.replace(/\b(ok|warn|bad|dim)\b/g, "").trim() + " " + cls;
    });
  }
  function stateToClass(state) {
    if (!state) return "dim";
    if (state === "SAFE" || state === "OK" || state === "LIVE") return "ok";
    if (state === "WARNING") return "warn";
    if (state === "CRITICAL") return "bad";
    return "dim";
  }

  function poll() {
    fetch("/api/telemetry/snapshot", { credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) throw new Error("http " + r.status);
        return r.json();
      })
      .then(function (s) {
        var lst = s.lst_hours;
        var ra = s.ra_hours;
        var hra =
          lst !== null && ra !== null && lst !== undefined && ra !== undefined
            ? ((lst - ra) % 24 + 24) % 24
            : null;
        var map = {
          ra: fmtHMS(ra),
          dec: fmtDMS(s.dec_deg),
          hra: fmtHMS(hra),
          az: fmtDeg(s.az_deg),
          alt: fmtDeg(s.alt_deg),
          lst:
            fmtHMS(lst) +
            (s.lst_source && s.lst_source !== "ALPACA" ? " *" : ""),
          tracking:
            s.tracking === true ? "ON" : s.tracking === false ? "OFF" : "UNKNOWN",
          motion:
            s.slewing === true
              ? "SLEWING"
              : s.slewing === false
                ? "IDLE"
                : "UNKNOWN",
          safety: (s.safety && s.safety.overall) || "UNKNOWN",
        };
        Object.keys(map).forEach(function (k) {
          setText('[data-live="' + k + '"]', map[k]);
        });

        /* -- Weather values -------------------------------- */
        var w = (s.weather && s.weather.values) || {};
        setText(
          '[data-live="temp"]',
          w.temp_c != null ? w.temp_c + " \u00b0C" : "\u2014"
        );
        setText(
          '[data-live="hum"]',
          w.humidity_pct != null ? w.humidity_pct + " %" : "\u2014"
        );
        setText(
          '[data-live="dew"]',
          w.dew_point_c != null ? w.dew_point_c + " \u00b0C" : "\u2014"
        );

        /* -- Environment/safety breakdown ------------------ */
        var env = s.environment || {};
        setText('[data-live="wx-status"]', env.weather_status || "UNKNOWN");
        setText(
          '[data-live="wx-age"]',
          (env.weather_age_fmt || "\u2014") + " ago"
        );
        setText('[data-live="hum-state"]', env.humidity_state || "\u2014");
        setText(
          '[data-live="wind-state"]',
          env.wind_state || "NOT AVAILABLE"
        );
        setText(
          '[data-live="rain-state"]',
          env.rain_state || "NOT AVAILABLE"
        );
        setText('[data-live="alt-state"]', env.altitude_state || "\u2014");

        /* -- Update safety class indicators ---------------- */
        setClass('[data-live="hum-state"]', stateToClass(env.humidity_state));
        setClass('[data-live="wind-state"]', stateToClass(env.wind_state));
        setClass('[data-live="rain-state"]', stateToClass(env.rain_state));
        setClass('[data-live="alt-state"]', stateToClass(env.altitude_state));
        setClass(
          '[data-live="wx-status"]',
          stateToClass(env.weather_status)
        );
      })
      .catch(function () {
        /* keep last rendered values */
      });
  }

  poll();
  setInterval(poll, 3000);

  /* -- Sub-tab switching (admin / system pages) ------------ */
  document.querySelectorAll("[data-subtab]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var bar = btn.parentElement;
      bar.querySelectorAll("button").forEach(function (b) {
        b.classList.remove("on");
      });
      btn.classList.add("on");
      var scope = btn.closest(".ws") || document;
      scope.querySelectorAll("[data-pane]").forEach(function (p) {
        p.style.display =
          p.getAttribute("data-pane") === btn.getAttribute("data-subtab")
            ? ""
            : "none";
      });
    });
  });
})();
