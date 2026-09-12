/* Self-contained chart layer for the Oura dashboard.
   No external libraries: charts are SVG built from the DATA blob the page
   embeds, redrawn on resize, range change and theme change. */
(function () {
  "use strict";

  var DATA = window.__OURA__ || { days: [] };
  var days = DATA.days || [];
  var range = 90;
  var SVGNS = "http://www.w3.org/2000/svg";

  function el(tag, attrs, text) {
    var node = document.createElementNS(SVGNS, tag);
    for (var key in attrs) {
      if (attrs[key] !== null && attrs[key] !== undefined) {
        node.setAttribute(key, attrs[key]);
      }
    }
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function css(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function slice() {
    return range >= days.length ? days.slice() : days.slice(days.length - range);
  }

  function present(rows, key) {
    var out = [];
    for (var i = 0; i < rows.length; i++) {
      var v = rows[i][key];
      if (v !== null && v !== undefined) out.push(v);
    }
    return out;
  }

  function extent(values, pad) {
    if (!values.length) return [0, 1];
    var lo = Math.min.apply(null, values);
    var hi = Math.max.apply(null, values);
    if (lo === hi) { lo -= 1; hi += 1; }
    var span = (hi - lo) * (pad === undefined ? 0.12 : pad);
    return [lo - span, hi + span];
  }

  function niceTicks(lo, hi, count) {
    var span = hi - lo;
    if (span <= 0) return [lo];
    var raw = span / Math.max(count, 1);
    var mag = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10));
    var norm = raw / mag;
    var step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
    var ticks = [];
    for (var t = Math.ceil(lo / step) * step; t <= hi + 1e-9; t += step) {
      ticks.push(Math.round(t * 1e6) / 1e6);
    }
    return ticks;
  }

  function fmtDay(iso, withYear) {
    var parts = String(iso).split("-");
    var d = new Date(Date.UTC(+parts[0], +parts[1] - 1, +parts[2]));
    var opts = { month: "short", day: "numeric", timeZone: "UTC" };
    if (withYear) opts.year = "numeric";
    return d.toLocaleDateString(undefined, opts);
  }

  function fmtNum(value, digits, unit) {
    if (value === null || value === undefined) return "--";
    var text = digits ? value.toFixed(digits) : Math.round(value).toLocaleString();
    return text + (unit || "");
  }

  function fmtHours(hours) {
    if (hours === null || hours === undefined) return "--";
    var total = Math.round(Math.abs(hours) * 60);
    return (hours < 0 ? "-" : "") + Math.floor(total / 60) + "h " +
      String(total % 60).padStart(2, "0") + "m";
  }

  function fmtClock(hours) {
    if (hours === null || hours === undefined) return "--";
    var total = Math.round(((hours % 24) + 24) % 24 * 60);
    return String(Math.floor(total / 60) % 24).padStart(2, "0") + ":" +
      String(total % 60).padStart(2, "0");
  }

  /* -- tooltip ------------------------------------------------------- */
  function makeTip(host) {
    var tip = document.createElement("div");
    tip.className = "tip";
    host.appendChild(tip);
    return {
      show: function (html, x, y) {
        tip.innerHTML = html;
        tip.setAttribute("data-show", "1");
        var box = host.getBoundingClientRect();
        var width = tip.offsetWidth;
        var left = Math.max(2, Math.min(x + 14, box.width - width - 2));
        tip.style.left = left + "px";
        tip.style.top = Math.max(0, y - tip.offsetHeight - 12) + "px";
      },
      hide: function () { tip.removeAttribute("data-show"); }
    };
  }

  function tipRows(rowsHtml, dayLabel) {
    return '<div class="tip-day">' + dayLabel + "</div>" + rowsHtml;
  }

  function tipRow(color, label, value) {
    return '<div class="tip-row"><span class="k">' +
      (color ? '<span class="swatch" style="background:' + color + '"></span>' : "") +
      label + '</span><span class="v">' + value + "</span></div>";
  }

  /* -- shared frame -------------------------------------------------- */
  function frame(host, opts) {
    var width = Math.max(host.clientWidth || 520, 260);
    var height = opts.height || 210;
    var pad = opts.pad || { top: 12, right: opts.padRight || 16, bottom: 26, left: 42 };
    var svg = el("svg", {
      viewBox: "0 0 " + width + " " + height,
      width: width, height: height,
      role: "img", "aria-label": opts.label || ""
    });
    host.innerHTML = "";
    host.appendChild(svg);
    return {
      svg: svg, width: width, height: height, pad: pad,
      iw: width - pad.left - pad.right,
      ih: height - pad.top - pad.bottom
    };
  }

  function yAxis(f, lo, hi, fmt) {
    var ticks = niceTicks(lo, hi, 4);
    var grid = css("--grid");
    for (var i = 0; i < ticks.length; i++) {
      var y = f.pad.top + f.ih - ((ticks[i] - lo) / (hi - lo)) * f.ih;
      f.svg.appendChild(el("line", {
        x1: f.pad.left, x2: f.pad.left + f.iw, y1: y, y2: y,
        stroke: grid, "stroke-width": 1
      }));
      f.svg.appendChild(el("text", {
        x: f.pad.left - 8, y: y + 4, "text-anchor": "end"
      }, fmt ? fmt(ticks[i]) : ticks[i]));
    }
  }

  function xLabels(f, rows, everyN) {
    if (!rows.length) return;
    var step = everyN || Math.max(1, Math.ceil(rows.length / 6));
    for (var i = rows.length - 1; i >= 0; i -= step) {
      var x = f.pad.left + (rows.length === 1 ? f.iw / 2 : (i / (rows.length - 1)) * f.iw);
      f.svg.appendChild(el("text", {
        x: x, y: f.height - 8, "text-anchor": "middle"
      }, fmtDay(rows[i].day)));
    }
    f.svg.appendChild(el("line", {
      x1: f.pad.left, x2: f.pad.left + f.iw,
      y1: f.pad.top + f.ih, y2: f.pad.top + f.ih,
      stroke: css("--axis"), "stroke-width": 1
    }));
  }


  function gutterFor(label) {
    // ~6px per character at 11px, plus the 5px offset and a little air.
    return label ? Math.max(20, String(label).length * 6 + 12) : 16;
  }

  function targetLine(f, value, label, py) {
    f.svg.appendChild(el("line", {
      x1: f.pad.left, x2: f.pad.left + f.iw, y1: py(value), y2: py(value),
      stroke: css("--axis"), "stroke-width": 1
    }));
    // Label lives in the right gutter, never over the data.
    f.svg.appendChild(el("text", {
      x: f.pad.left + f.iw + 5, y: py(value) + 4, "text-anchor": "start"
    }, label || "target"));
  }

  /* -- line chart (crosshair tooltip, direct end-labels) ------------- */
  function lineChart(host, spec) {
    var rows = slice();
    var all = [];
    spec.series.forEach(function (s) { all = all.concat(present(rows, s.key)); });
    if (!all.length) { host.innerHTML = '<p class="note">No data yet.</p>'; return; }

    var bounds = extent(all, 0.12);
    if (spec.zeroFloor && bounds[0] < 0) bounds[0] = 0;
    var lo = bounds[0], hi = bounds[1];
    var needsLabelRoom = spec.series.length > 1;
    var hasTarget = spec.target !== undefined && spec.target !== null;
    var f = frame(host, {
      height: spec.height || 226,
      padRight: needsLabelRoom ? 52 : (hasTarget ? gutterFor(spec.targetLabel || "target") : 16),
      label: spec.label
    });
    yAxis(f, lo, hi, spec.yFmt);
    xLabels(f, rows);

    function px(i) {
      return f.pad.left + (rows.length === 1 ? f.iw / 2 : (i / (rows.length - 1)) * f.iw);
    }
    function py(v) { return f.pad.top + f.ih - ((v - lo) / (hi - lo)) * f.ih; }

    if (hasTarget && spec.target >= lo && spec.target <= hi) {
      targetLine(f, spec.target, spec.targetLabel, py);
    }

    var endLabels = [];
    spec.series.forEach(function (s) {
      var color = css(s.color);
      var run = [];
      var lastPoint = null;
      function flush() {
        if (run.length > 1) {
          f.svg.appendChild(el("path", {
            d: "M" + run.join("L"), fill: "none", stroke: color,
            "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round"
          }));
        } else if (run.length === 1) {
          var xy = run[0].split(",");
          f.svg.appendChild(el("circle", {
            cx: xy[0], cy: xy[1], r: 2.5, fill: color
          }));
        }
        run = [];
      }
      for (var i = 0; i < rows.length; i++) {
        var v = rows[i][s.key];
        if (v === null || v === undefined) { flush(); continue; }
        run.push(px(i) + "," + py(v));
        lastPoint = { x: px(i), y: py(v), v: v };
      }
      flush();
      if (lastPoint) {
        f.svg.appendChild(el("circle", {
          cx: lastPoint.x, cy: lastPoint.y, r: 4,
          fill: color, stroke: css("--surface-1"), "stroke-width": 2
        }));
        // Direct end-label: identity never rests on color alone.
        if (needsLabelRoom) {
          endLabels.push({ y: lastPoint.y, x: lastPoint.x, text: s.short || s.label });
        }
      }
    });

    // Nudge colliding end-labels apart rather than stacking them.
    endLabels.sort(function (a, b) { return a.y - b.y; });
    var minGap = 13;
    for (var li = 1; li < endLabels.length; li++) {
      if (endLabels[li].y - endLabels[li - 1].y < minGap) {
        endLabels[li].y = endLabels[li - 1].y + minGap;
      }
    }
    var overflow = endLabels.length
      ? endLabels[endLabels.length - 1].y - (f.pad.top + f.ih)
      : 0;
    if (overflow > 0) {
      endLabels.forEach(function (label) { label.y -= overflow; });
    }
    endLabels.forEach(function (label) {
      f.svg.appendChild(el("text", {
        x: label.x + 8, y: label.y + 4, "text-anchor": "start",
        fill: css("--text-secondary")
      }, label.text));
    });

    var crosshair = el("line", {
      y1: f.pad.top, y2: f.pad.top + f.ih, stroke: css("--axis"),
      "stroke-width": 1, opacity: 0
    });
    f.svg.appendChild(crosshair);
    var tip = makeTip(host);

    f.svg.appendChild(el("rect", {
      x: f.pad.left, y: f.pad.top, width: f.iw, height: f.ih,
      fill: "transparent", style: "cursor:crosshair"
    }));
    var hit = f.svg.lastChild;

    function move(event) {
      var box = f.svg.getBoundingClientRect();
      var scale = f.width / box.width;
      var mx = (event.clientX - box.left) * scale;
      var ratio = (mx - f.pad.left) / f.iw;
      var index = Math.round(ratio * (rows.length - 1));
      index = Math.max(0, Math.min(rows.length - 1, index));
      var row = rows[index];
      var html = "";
      spec.series.forEach(function (s) {
        var v = row[s.key];
        html += tipRow(css(s.color), s.label,
          v === null || v === undefined ? "--" : (spec.tipFmt || spec.yFmt || fmtNum)(v));
      });
      crosshair.setAttribute("x1", px(index));
      crosshair.setAttribute("x2", px(index));
      crosshair.setAttribute("opacity", 1);
      tip.show(tipRows(html, fmtDay(row.day, true)), px(index) / scale, f.pad.top + 10);
    }
    hit.addEventListener("mousemove", move);
    hit.addEventListener("touchstart", function (e) {
      if (e.touches[0]) move(e.touches[0]);
    }, { passive: true });
    hit.addEventListener("mouseleave", function () {
      crosshair.setAttribute("opacity", 0);
      tip.hide();
    });
  }

  /* -- bar chart ----------------------------------------------------- */
  function barChart(host, spec) {
    var rows = slice();
    var values = present(rows, spec.key);
    if (!values.length) { host.innerHTML = '<p class="note">No data yet.</p>'; return; }

    var hi = Math.max.apply(null, values);
    if (spec.target) hi = Math.max(hi, spec.target);
    hi *= 1.1;
    var lo = 0;
    var f = frame(host, {
      height: spec.height || 226,
      padRight: spec.target ? gutterFor(spec.targetLabel || "target") : 16,
      label: spec.label
    });
    yAxis(f, lo, hi, spec.yFmt);
    xLabels(f, rows);

    var band = f.iw / rows.length;
    var barWidth = Math.max(2, Math.min(24, band - 2)); // 2px surface gap, capped
    var tip = makeTip(host);
    var color = css(spec.color);

    function py(v) { return f.pad.top + f.ih - ((v - lo) / (hi - lo)) * f.ih; }

    rows.forEach(function (row, i) {
      var v = row[spec.key];
      var cx = f.pad.left + band * (i + 0.5);
      if (v === null || v === undefined) return;
      var y = py(v);
      var barHeight = Math.max(1, f.pad.top + f.ih - y);
      var fill = color;
      var radius = Math.min(4, barWidth / 2);
      f.svg.appendChild(el("path", {
        // Rounded data-end, square at the baseline.
        d: "M" + (cx - barWidth / 2) + "," + (y + barHeight) +
           "V" + (y + radius) +
           "a" + radius + "," + radius + " 0 0 1 " + radius + "," + -radius +
           "h" + (barWidth - 2 * radius) +
           "a" + radius + "," + radius + " 0 0 1 " + radius + "," + radius +
           "V" + (y + barHeight) + "Z",
        fill: fill
      }));
      var hit = el("rect", {
        x: cx - band / 2, y: f.pad.top, width: band, height: f.ih,
        fill: "transparent"
      });
      hit.addEventListener("mouseenter", function () {
        tip.show(tipRows(tipRow(fill, spec.label, (spec.tipFmt || spec.yFmt || fmtNum)(v)),
          fmtDay(row.day, true)), cx, y);
      });
      hit.addEventListener("mouseleave", tip.hide);
      f.svg.appendChild(hit);
    });

    if (spec.target) {
      targetLine(f, spec.target, spec.targetLabel, py);
    }
  }

  /* -- stacked bars (sleep stages) ----------------------------------- */
  function stackedChart(host, spec) {
    var rows = slice();
    var totals = rows.map(function (row) {
      return spec.series.reduce(function (sum, s) {
        var v = row[s.key];
        return sum + (v === null || v === undefined ? 0 : v);
      }, 0);
    }).filter(function (t) { return t > 0; });
    if (!totals.length) { host.innerHTML = '<p class="note">No data yet.</p>'; return; }

    var hi = Math.max.apply(null, totals) * 1.1;
    var f = frame(host, { height: spec.height || 226, label: spec.label });
    yAxis(f, 0, hi, spec.yFmt);
    xLabels(f, rows);

    var band = f.iw / rows.length;
    var barWidth = Math.max(2, Math.min(24, band - 2));
    var tip = makeTip(host);

    rows.forEach(function (row, i) {
      var cx = f.pad.left + band * (i + 0.5);
      var cursor = 0;
      var html = "";
      var top = f.pad.top + f.ih;
      spec.series.forEach(function (s) {
        var v = row[s.key];
        html += tipRow(css(s.color), s.label, (spec.tipFmt || fmtHours)(v));
        if (v === null || v === undefined || v <= 0) return;
        var y0 = f.pad.top + f.ih - (cursor / hi) * f.ih;
        var y1 = f.pad.top + f.ih - ((cursor + v) / hi) * f.ih;
        var height = Math.max(1, y0 - y1 - 2); // 2px surface gap between segments
        f.svg.appendChild(el("rect", {
          x: cx - barWidth / 2, y: y1, width: barWidth, height: height,
          fill: css(s.color), rx: 1
        }));
        cursor += v;
        top = Math.min(top, y1);
      });
      var hit = el("rect", {
        x: cx - band / 2, y: f.pad.top, width: band, height: f.ih, fill: "transparent"
      });
      var totalHtml = html;
      hit.addEventListener("mouseenter", function () {
        tip.show(tipRows(totalHtml, fmtDay(row.day, true)), cx, top);
      });
      hit.addEventListener("mouseleave", tip.hide);
      f.svg.appendChild(hit);
    });
  }

  /* -- sleep window range bars --------------------------------------- */
  function rangeChart(host, spec) {
    var rows = slice().filter(function (r) {
      return r.bedtime_start_h !== null && r.bedtime_start_h !== undefined &&
             r.bedtime_end_h !== null && r.bedtime_end_h !== undefined;
    });
    if (!rows.length) { host.innerHTML = '<p class="note">No data yet.</p>'; return; }

    var starts = rows.map(function (r) { return r.bedtime_start_h; });
    var ends = rows.map(function (r) { return r.bedtime_end_h; });
    var lo = Math.floor(Math.min.apply(null, starts) - 0.5);
    var hi = Math.ceil(Math.max.apply(null, ends) + 0.5);
    var f = frame(host, { height: spec.height || 226, label: spec.label });

    var ticks = niceTicks(lo, hi, 4);
    ticks.forEach(function (t) {
      var y = f.pad.top + f.ih - ((t - lo) / (hi - lo)) * f.ih;
      f.svg.appendChild(el("line", {
        x1: f.pad.left, x2: f.pad.left + f.iw, y1: y, y2: y,
        stroke: css("--grid"), "stroke-width": 1
      }));
      f.svg.appendChild(el("text", {
        x: f.pad.left - 8, y: y + 4, "text-anchor": "end"
      }, fmtClock(t)));
    });
    xLabels(f, rows);

    var band = f.iw / rows.length;
    var barWidth = Math.max(2, Math.min(14, band - 2));
    var color = css("--seq-450");
    var tip = makeTip(host);

    rows.forEach(function (row, i) {
      var cx = f.pad.left + band * (i + 0.5);
      var y1 = f.pad.top + f.ih - ((row.bedtime_start_h - lo) / (hi - lo)) * f.ih;
      var y2 = f.pad.top + f.ih - ((row.bedtime_end_h - lo) / (hi - lo)) * f.ih;
      f.svg.appendChild(el("rect", {
        x: cx - barWidth / 2, y: Math.min(y1, y2), width: barWidth,
        height: Math.max(2, Math.abs(y2 - y1)), fill: color, rx: 3
      }));
      var hit = el("rect", {
        x: cx - band / 2, y: f.pad.top, width: band, height: f.ih, fill: "transparent"
      });
      hit.addEventListener("mouseenter", function () {
        tip.show(tipRows(
          tipRow(color, "Asleep", fmtClock(row.bedtime_start_h)) +
          tipRow(null, "Awake", fmtClock(row.bedtime_end_h)) +
          tipRow(null, "Duration", fmtHours(row.total_sleep_h)),
          fmtDay(row.day, true)), cx, Math.min(y1, y2));
      });
      hit.addEventListener("mouseleave", tip.hide);
      f.svg.appendChild(hit);
    });
  }

  /* -- weekday pattern ----------------------------------------------- */
  function weekdayChart(host, spec) {
    var names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    var buckets = [[], [], [], [], [], [], []];
    slice().forEach(function (row) {
      if (row.sleep_score !== null && row.sleep_score !== undefined) {
        buckets[row.weekday].push(row.sleep_score);
      }
    });
    var averages = buckets.map(function (values) {
      if (!values.length) return null;
      return values.reduce(function (a, b) { return a + b; }, 0) / values.length;
    });
    var present_ = averages.filter(function (v) { return v !== null; });
    if (!present_.length) { host.innerHTML = '<p class="note">No data yet.</p>'; return; }

    var lo = Math.max(0, Math.min.apply(null, present_) - 8);
    var hi = Math.min(100, Math.max.apply(null, present_) + 6);
    var worst = Math.min.apply(null, present_);
    var f = frame(host, { height: spec.height || 200, label: spec.label });
    yAxis(f, lo, hi, function (v) { return Math.round(v); });

    var band = f.iw / 7;
    var barWidth = Math.max(8, Math.min(24, band - 12));
    var tip = makeTip(host);

    averages.forEach(function (value, i) {
      var cx = f.pad.left + band * (i + 0.5);
      f.svg.appendChild(el("text", {
        x: cx, y: f.height - 8, "text-anchor": "middle"
      }, names[i]));
      if (value === null) return;
      // Emphasis: the worst night is the point of this chart.
      var isWorst = value - worst < 0.5;
      var fill = css(isWorst ? "--series-2" : "--seq-300");
      var y = f.pad.top + f.ih - ((value - lo) / (hi - lo)) * f.ih;
      var height = Math.max(1, f.pad.top + f.ih - y);
      var radius = Math.min(4, barWidth / 2);
      f.svg.appendChild(el("path", {
        d: "M" + (cx - barWidth / 2) + "," + (y + height) +
           "V" + (y + radius) +
           "a" + radius + "," + radius + " 0 0 1 " + radius + "," + -radius +
           "h" + (barWidth - 2 * radius) +
           "a" + radius + "," + radius + " 0 0 1 " + radius + "," + radius +
           "V" + (y + height) + "Z",
        fill: fill
      }));
      f.svg.appendChild(el("text", {
        x: cx, y: y - 6, "text-anchor": "middle",
        fill: css("--text-secondary")
      }, Math.round(value)));
      var hit = el("rect", {
        x: cx - band / 2, y: f.pad.top, width: band, height: f.ih, fill: "transparent"
      });
      hit.addEventListener("mouseenter", function () {
        tip.show(tipRows(
          tipRow(fill, "Avg sleep score", Math.round(value)) +
          tipRow(null, "Nights", buckets[i].length), names[i]), cx, y);
      });
      hit.addEventListener("mouseleave", tip.hide);
      f.svg.appendChild(hit);
    });
    f.svg.appendChild(el("line", {
      x1: f.pad.left, x2: f.pad.left + f.iw,
      y1: f.pad.top + f.ih, y2: f.pad.top + f.ih,
      stroke: css("--axis"), "stroke-width": 1
    }));
  }

  /* -- sparklines in stat tiles -------------------------------------- */
  function sparkline(host, key) {
    var rows = days.slice(Math.max(0, days.length - 30));
    var values = present(rows, key);
    if (values.length < 2) { host.innerHTML = ""; return; }
    var bounds = extent(values, 0.15);
    var width = Math.max(host.clientWidth || 150, 80);
    var height = 34;
    var svg = el("svg", { viewBox: "0 0 " + width + " " + height, width: width, height: height, "aria-hidden": "true" });
    var color = css("--seq-450");
    var points = [];
    var last = null;
    rows.forEach(function (row, i) {
      var v = row[key];
      if (v === null || v === undefined) return;
      var x = (i / (rows.length - 1)) * (width - 6) + 3;
      var y = height - 4 - ((v - bounds[0]) / (bounds[1] - bounds[0])) * (height - 8);
      points.push(x + "," + y);
      last = { x: x, y: y };
    });
    if (points.length > 1) {
      svg.appendChild(el("path", {
        d: "M" + points.join("L"), fill: "none", stroke: color,
        "stroke-width": 2, "stroke-linecap": "round", "stroke-linejoin": "round"
      }));
    }
    if (last) {
      svg.appendChild(el("circle", {
        cx: last.x, cy: last.y, r: 3, fill: color,
        stroke: css("--surface-1"), "stroke-width": 2
      }));
    }
    host.innerHTML = "";
    host.appendChild(svg);
  }

  /* -- wiring -------------------------------------------------------- */
  var CHARTS = {
    scores: function (host) {
      lineChart(host, {
        label: "Sleep, readiness and activity scores over time",
        series: [
          { key: "readiness_score", label: "Readiness", short: "Readiness", color: "--series-1" },
          { key: "sleep_score", label: "Sleep", short: "Sleep", color: "--series-2" },
          { key: "activity_score", label: "Activity", short: "Activity", color: "--series-3" }
        ],
        yFmt: function (v) { return Math.round(v); },
        tipFmt: function (v) { return Math.round(v); },
        height: 250
      });
    },
    sleepDuration: function (host) {
      barChart(host, {
        label: "Nightly sleep duration",
        key: "total_sleep_h", color: "--seq-450",
        target: DATA.meta.sleep_need_h, targetLabel: "need",
        yFmt: function (v) { return v.toFixed(0) + "h"; },
        tipFmt: fmtHours
      });
    },
    stages: function (host) {
      stackedChart(host, {
        label: "Sleep stages per night",
        series: [
          { key: "deep_h", label: "Deep", color: "--seq-700" },
          { key: "rem_h", label: "REM", color: "--seq-450" },
          { key: "light_h", label: "Light", color: "--seq-250" },
          { key: "awake_h", label: "Awake", color: "--neutral-fill" }
        ],
        yFmt: function (v) { return v.toFixed(0) + "h"; },
        tipFmt: fmtHours
      });
    },
    hrv: function (host) {
      lineChart(host, {
        label: "Average overnight HRV",
        series: [{ key: "avg_hrv", label: "HRV", color: "--series-1" }],
        yFmt: function (v) { return Math.round(v); },
        tipFmt: function (v) { return Math.round(v) + " ms"; }
      });
    },
    rhr: function (host) {
      lineChart(host, {
        label: "Lowest overnight heart rate",
        series: [{ key: "lowest_hr", label: "Resting HR", color: "--series-2" }],
        yFmt: function (v) { return Math.round(v); },
        tipFmt: function (v) { return Math.round(v) + " bpm"; }
      });
    },
    steps: function (host) {
      barChart(host, {
        label: "Daily steps",
        key: "steps", color: "--seq-450", target: 8000, targetLabel: "8k",
        yFmt: function (v) { return v >= 1000 ? (v / 1000).toFixed(0) + "k" : String(Math.round(v)); },
        tipFmt: function (v) { return Math.round(v).toLocaleString() + " steps"; }
      });
    },
    window: function (host) {
      rangeChart(host, { label: "Nightly sleep window" });
    },
    weekday: function (host) {
      weekdayChart(host, { label: "Average sleep score by weekday" });
    },
    stress: function (host) {
      lineChart(host, {
        label: "Daytime stress and restorative minutes",
        series: [
          { key: "stress_high_min", label: "High stress", short: "Stress", color: "--series-2" },
          { key: "recovery_high_min", label: "Restorative", short: "Restored", color: "--series-3" }
        ],
        zeroFloor: true,
        yFmt: function (v) { return Math.round(v); },
        tipFmt: function (v) { return Math.round(v) + " min"; }
      });
    },
    temperature: function (host) {
      lineChart(host, {
        label: "Body temperature deviation",
        series: [{ key: "temperature_deviation", label: "Temp deviation", color: "--series-2" }],
        target: 0, targetLabel: "base",
        yFmt: function (v) { return v.toFixed(1); },
        tipFmt: function (v) { return (v > 0 ? "+" : "") + v.toFixed(2) + "°C"; }
      });
    },
    efficiency: function (host) {
      lineChart(host, {
        label: "Sleep efficiency",
        series: [{ key: "efficiency", label: "Efficiency", color: "--series-1" }],
        target: 85, targetLabel: "85%",
        yFmt: function (v) { return Math.round(v) + "%"; },
        tipFmt: function (v) { return Math.round(v) + "%"; }
      });
    },
    spo2: function (host) {
      lineChart(host, {
        label: "Overnight blood oxygen",
        series: [{ key: "spo2_avg", label: "SpO₂", color: "--series-1" }],
        target: 94, targetLabel: "94%",
        yFmt: function (v) { return v.toFixed(0) + "%"; },
        tipFmt: function (v) { return v.toFixed(1) + "%"; }
      });
    }
  };

  function renderAll() {
    Object.keys(CHARTS).forEach(function (name) {
      var host = document.querySelector('[data-chart="' + name + '"]');
      if (host) {
        try { CHARTS[name](host); }
        catch (err) { host.innerHTML = '<p class="note">Chart unavailable.</p>'; }
      }
    });
    document.querySelectorAll("[data-spark]").forEach(function (host) {
      try { sparkline(host, host.getAttribute("data-spark")); } catch (err) { host.innerHTML = ""; }
    });
  }

  function setRange(value) {
    range = value;
    document.querySelectorAll("[data-range]").forEach(function (button) {
      button.setAttribute("aria-pressed",
        String(Number(button.getAttribute("data-range")) === value));
    });
    renderAll();
  }

  document.querySelectorAll("[data-range]").forEach(function (button) {
    button.addEventListener("click", function () {
      setRange(Number(button.getAttribute("data-range")));
    });
  });

  var timer = null;
  window.addEventListener("resize", function () {
    clearTimeout(timer);
    timer = setTimeout(renderAll, 140);
  });

  if (window.matchMedia) {
    var scheme = window.matchMedia("(prefers-color-scheme: dark)");
    if (scheme.addEventListener) scheme.addEventListener("change", renderAll);
  }
  new MutationObserver(renderAll).observe(document.documentElement, {
    attributes: true, attributeFilter: ["data-theme"]
  });

  setRange(Math.min(90, Math.max(days.length, 7)));
})();
