/* Deterministic meta-analysis panel — same math as askbench/clinical.py, runs in-browser. */
(function (global) {
  "use strict";

  var FIELD_ALIASES = {
    factor: ["factor", "risk_factor", "exposure", "treatment", "arm", "group", "intervention"],
    study: ["study", "population", "trial", "label", "cohort", "author", "reference", "paper"],
    n: ["n", "sample_size", "total", "participants", "patients"],
    outcome: ["outcome", "endpoint"],
    log_rr: ["log_rr", "logrr", "ln_rr", "log_or", "log_hr"],
    se: ["se", "stderr", "standard_error", "sem"],
    rr: ["rr", "risk_ratio", "or", "odds_ratio", "hr", "hazard_ratio", "effect"],
    ci_low: ["ci_low", "ci_lower", "lower", "lcl", "lower_ci", "lo_95", "ci_lo"],
    ci_high: ["ci_high", "ci_upper", "upper", "ucl", "upper_ci", "hi_95", "ci_hi"]
  };

  function normHeader(h) {
    return String(h || "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
  }

  function parseCsvRows(text) {
    var rows = [];
    var row = [];
    var cell = "";
    var inQuotes = false;
    for (var i = 0; i < text.length; i++) {
      var c = text[i];
      if (inQuotes) {
        if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; }
        else if (c === '"') inQuotes = false;
        else cell += c;
      } else if (c === '"') inQuotes = true;
      else if (c === ",") { row.push(cell); cell = ""; }
      else if (c === "\n" || c === "\r") {
        if (c === "\r" && text[i + 1] === "\n") i++;
        row.push(cell); cell = "";
        if (row.some(function (x) { return String(x).trim(); })) rows.push(row);
        row = [];
      } else cell += c;
    }
    if (cell.length || row.length) {
      row.push(cell);
      if (row.some(function (x) { return String(x).trim(); })) rows.push(row);
    }
    return rows;
  }

  function headersFromCsv(text) {
    var rows = parseCsvRows((text || "").trim());
    if (!rows.length) return [];
    return rows[0].map(function (h) { return String(h).trim(); });
  }

  function suggestColumnMap(headers) {
    var norms = headers.map(normHeader);
    var map = { factor: "", study: "", n: "", outcome: "", log_rr: "", se: "", rr: "", ci_low: "", ci_high: "" };
    function pick(role) {
      var aliases = FIELD_ALIASES[role] || [];
      for (var i = 0; i < norms.length; i++) {
        for (var j = 0; j < aliases.length; j++) {
          if (norms[i] === aliases[j]) return headers[i];
        }
      }
      return "";
    }
    Object.keys(map).forEach(function (role) { map[role] = pick(role); });
    return map;
  }

  function mapOk(map) {
    if (!map || !map.factor) return false;
    if (map.log_rr && map.se) return true;
    if (map.rr && map.se) return true;
    if (map.rr && map.ci_low && map.ci_high) return true;
    return false;
  }

  function colIndex(headers, name) {
    if (!name) return -1;
    var target = normHeader(name);
    for (var i = 0; i < headers.length; i++) {
      if (normHeader(headers[i]) === target) return i;
    }
    return headers.indexOf(name);
  }

  function fnum(val) {
    if (val == null) return null;
    var s = String(val).trim();
    if (!s) return null;
    var n = parseFloat(s);
    return isFinite(n) ? n : null;
  }

  function parseStudies(text, map, outcomeArg) {
    text = (text || "").trim();
    if (!text) return { ok: false, error: "Paste a CSV table with your study results." };
    if (text.length > 65536) return { ok: false, error: "Table is too large (max 64 KB)." };
    if (!mapOk(map)) return { ok: false, error: "Map columns: need factor plus log_rr+se, rr+se, or rr with both CIs." };

    var rows = parseCsvRows(text);
    if (rows.length < 2) return { ok: false, error: "Need a header row and at least one study." };

    var headers = rows[0].map(function (h) { return String(h).trim(); });
    var fi = colIndex(headers, map.factor);
    var si = colIndex(headers, map.study);
    var ni = colIndex(headers, map.n);
    var oi = colIndex(headers, map.outcome);
    var li = colIndex(headers, map.log_rr);
    var sei = colIndex(headers, map.se);
    var ri = colIndex(headers, map.rr);
    var loi = colIndex(headers, map.ci_low);
    var hii = colIndex(headers, map.ci_high);

    var studies = [];
    var seenOutcome = null;
    for (var r = 1; r < rows.length; r++) {
      var cells = rows[r];
      var factor = fi >= 0 ? String(cells[fi] || "").trim() : "";
      if (!factor) continue;

      var pop = si >= 0 ? String(cells[si] || "").trim() : "";
      if (!pop) pop = "Study " + (studies.length + 1);

      var nVal = ni >= 0 ? fnum(cells[ni]) : null;
      var n = nVal && nVal > 0 ? Math.round(nVal) : 100;

      if (oi >= 0) {
        var o = String(cells[oi] || "").trim();
        if (o) seenOutcome = o;
      }

      var logRr = li >= 0 ? fnum(cells[li]) : null;
      var se = sei >= 0 ? fnum(cells[sei]) : null;
      var rr = ri >= 0 ? fnum(cells[ri]) : null;
      var ciLo = loi >= 0 ? fnum(cells[loi]) : null;
      var ciHi = hii >= 0 ? fnum(cells[hii]) : null;

      if (logRr == null && rr != null && rr > 0) logRr = Math.log(rr);
      if (se == null && rr && ciLo && ciHi && ciLo > 0 && ciHi > 0) {
        se = (Math.log(ciHi) - Math.log(ciLo)) / (2 * 1.96);
      }
      if (se == null && rr && rr > 0) se = 0.2;

      if (logRr == null || se == null || se <= 0) {
        return { ok: false, error: "Row " + r + " (" + factor + "): need effect + uncertainty (SE or CI)." };
      }

      studies.push({
        factor: factor,
        population: pop,
        log_rr: Math.round(logRr * 1e6) / 1e6,
        se: Math.round(se * 1e6) / 1e6,
        n: n,
        rr: Math.round(Math.exp(logRr) * 100) / 100,
        ci_low: Math.round(Math.exp(logRr - 1.96 * se) * 100) / 100,
        ci_high: Math.round(Math.exp(logRr + 1.96 * se) * 100) / 100
      });
    }

    if (!studies.length) {
      return { ok: false, error: "No study rows parsed. Check factor column mapping." };
    }

    var factors = {};
    studies.forEach(function (s) { factors[s.factor] = true; });
    var outcome = (seenOutcome || outcomeArg || "outcome").trim() || "outcome";

    return {
      ok: true,
      studies: studies,
      outcome: outcome,
      factorCount: Object.keys(factors).length,
      data_note: "Your pasted table (" + studies.length + " study rows, " +
        Object.keys(factors).length + " factor(s)). Outcome: " + outcome +
        ". Computed locally in your browser — same toolkit math as the server."
    };
  }

  function poolRandomEffects(studies) {
    var k = studies.length;
    if (!k) return { k: 0, error: "no studies" };
    var ys = studies.map(function (s) { return s.log_rr; });
    var vs = studies.map(function (s) { return s.se * s.se; });
    var ws = vs.map(function (v) { return 1.0 / v; });
    var sw = ws.reduce(function (a, b) { return a + b; }, 0);
    var yFixed = ys.reduce(function (acc, y, i) { return acc + ws[i] * y; }, 0) / sw;
    var q = ys.reduce(function (acc, y, i) { return acc + ws[i] * (y - yFixed) * (y - yFixed); }, 0);
    var df = k - 1;
    var sumW2 = ws.reduce(function (a, w) { return a + w * w; }, 0);
    var c = sw - sumW2 / sw;
    var tau2 = c > 0 ? Math.max(0, (q - df) / c) : 0;
    var wsStar = vs.map(function (v) { return 1.0 / (v + tau2); });
    var swStar = wsStar.reduce(function (a, b) { return a + b; }, 0);
    var yPooled = ys.reduce(function (acc, y, i) { return acc + wsStar[i] * y; }, 0) / swStar;
    var sePooled = Math.sqrt(1.0 / swStar);
    var lo = yPooled - 1.96 * sePooled;
    var hi = yPooled + 1.96 * sePooled;
    var i2 = q > 0 ? Math.max(0, (q - df) / q) * 100 : 0;
    return {
      k: k,
      rr: Math.round(Math.exp(yPooled) * 1000) / 1000,
      ci_low: Math.round(Math.exp(lo) * 1000) / 1000,
      ci_high: Math.round(Math.exp(hi) * 1000) / 1000,
      i2: Math.round(i2 * 10) / 10,
      q: Math.round(q * 1000) / 1000,
      tau2: Math.round(tau2 * 10000) / 10000,
      n_total: studies.reduce(function (a, s) { return a + s.n; }, 0),
      significant: lo > 0 || hi < 0
    };
  }

  function metaSkepticFlags(row, maxI2, minStudies) {
    maxI2 = maxI2 == null ? 75 : maxI2;
    minStudies = minStudies == null ? 3 : minStudies;
    var flags = [];
    if (!row.k || row.error) return ["no studies to pool"];
    if (row.k < minStudies) {
      flags.push("pooled from only " + row.k + " studies (under " + minStudies + "); the estimate is fragile");
    }
    if (row.i2 > maxI2) {
      flags.push("high heterogeneity (I²=" + row.i2 + "%); the effect varies too much across populations to trust as one pooled number");
    }
    if (!row.significant) {
      flags.push("confidence interval crosses no-effect (RR " + row.ci_low + " to " + row.ci_high + "); not significant");
    } else if (row.rr >= 0.9 && row.rr <= 1.11) {
      flags.push("effect is clinically negligible (pooled RR " + row.rr + " sits inside the null band 0.90 to 1.11)");
    }
    return flags;
  }

  function rankFactors(studies) {
    var byFactor = {};
    studies.forEach(function (s) {
      if (!byFactor[s.factor]) byFactor[s.factor] = [];
      byFactor[s.factor].push(s);
    });
    var rows = Object.keys(byFactor).map(function (f) {
      var pooled = poolRandomEffects(byFactor[f]);
      pooled.factor = f;
      return pooled;
    });
    rows.sort(function (a, b) { return (b.rr || 0) - (a.rr || 0); });
    return rows;
  }

  function focusedAnswer(question, vetted, outcome) {
    var q = String(question || "").toLowerCase();
    var het = vetted.filter(function (v) {
      return v.verdict === "flagged" && (v.flags || []).some(function (f) { return /heterogen/i.test(f); });
    });
    var solid = vetted.filter(function (v) { return v.verdict === "solid"; });

    if (/heterogen|pool|trustworthy|one number|safe|report/.test(q) && het.length) {
      var h = het[0];
      return "Safe to report one pooled number for " + h.factor + ": No — I²=" + h.i2 +
        "% is too high. Pooling would hide disagreement across studies, not resolve it.";
    }
    if (/strongest|effect|largest/.test(q) && vetted.length) {
      var top = vetted[0];
      var tag = top.verdict === "solid" ? "passes" : "does not pass";
      return "Strongest pooled effect on " + outcome + ": " + top.factor + " (RR " + top.rr +
        ", 95% CI " + top.ci_low + " to " + top.ci_high + ", I²=" + top.i2 + "%) — " +
        tag + " the Skeptic's checks.";
    }
    if (solid.length) {
      var names = solid.map(function (v) {
        return v.factor + " (RR " + v.rr + ", " + v.k + " studies)";
      }).join("; ");
      return "Factors that pass the panel's checks for " + outcome + ": " + names + ".";
    }
    if (het.length) {
      var hf = het[0];
      return "No factor is safe to report as one pooled number. " + hf.factor +
        " is flagged: I²=" + hf.i2 + "% — too heterogeneous to pool honestly.";
    }
    return "No single factor passes the panel's checks cleanly for " + outcome + ".";
  }

  function synthesize(vetted, outcome) {
    return focusedAnswer("", vetted, outcome);
  }

  function safeReportLine(vetted) {
    var solid = vetted.filter(function (v) { return v.verdict === "solid"; });
    if (solid.length) {
      return "Safe to report one pooled number for " + solid[0].factor + ": Yes — passes study count, heterogeneity, and significance checks.";
    }
    var flagged = vetted.filter(function (v) { return v.verdict === "flagged"; });
    if (!flagged.length) return "";
    var h = flagged[0];
    if ((h.flags || []).some(function (f) { return /heterogen/i.test(f); })) {
      return "Safe to report one pooled number for " + h.factor + ": No — I²=" + h.i2 + "% (too heterogeneous).";
    }
    return "Safe to report one pooled number for " + h.factor + ": No — " + ((h.flags || [])[0] || "checks failed");
  }

  function stubDebate(vetted, answer) {
    var top = vetted[0];
    var skepticBits = (top.flags || []).join("; ") || "no flags on the lead factor";
    return [
      { agent: "Analyst", text: "I pooled each factor with random-effects meta-analysis and ranked by pooled RR." },
      { agent: "Skeptic", text: top.factor + ": " + skepticBits + "." },
      { agent: "Contextualist", text: "Biological interpretation is yours to judge; the statistics above are from the deterministic toolkit." },
      { agent: "Chair", text: answer }
    ];
  }

  function forestPlotSvg(outcome, vetted) {
    var items = vetted.slice().sort(function (a, b) { return b.rr - a.rr; });
    var rowH = 34;
    var padL = 180;
    var padR = 40;
    var w = 640;
    var h = 56 + items.length * rowH;
    var x0 = padL;
    var x1 = w - padR;
    var logMin = -1.5;
    var logMax = 1.5;
    function xPos(rr) {
      var lr = Math.log(Math.max(0.05, rr));
      return x0 + ((lr - logMin) / (logMax - logMin)) * (x1 - x0);
    }
    var mid = xPos(1);
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="' + w + '" height="' + h + '">' +
      '<rect width="100%" height="100%" fill="#fafbfc"/>' +
      '<text x="' + padL + '" y="22" font-family="system-ui,sans-serif" font-size="13" font-weight="600" fill="#1f2933">Pooled RR — ' + outcome + '</text>' +
      '<line x1="' + mid + '" y1="40" x2="' + mid + '" y2="' + (h - 16) + '" stroke="#c5ced6" stroke-dasharray="4 4"/>' +
      '<text x="' + mid + '" y="' + (h - 4) + '" text-anchor="middle" font-size="10" fill="#8a97a3">RR = 1</text>';
    items.forEach(function (f, i) {
      var y = 48 + i * rowH;
      var xc = xPos(f.rr);
      var xl = xPos(f.ci_low);
      var xh = xPos(f.ci_high);
      var col = f.verdict === "solid" ? "#2f6f4f" : "#99590f";
      svg += '<text x="8" y="' + (y + 4) + '" font-size="11" fill="#1f2933">' + escapeXml(f.factor) + '</text>';
      svg += '<line x1="' + xl + '" y1="' + y + '" x2="' + xh + '" y2="' + y + '" stroke="' + col + '" stroke-width="2"/>';
      svg += '<rect x="' + (xc - 4) + '" y="' + (y - 4) + '" width="8" height="8" fill="' + col + '"/>';
      svg += '<text x="' + (x1 + 6) + '" y="' + (y + 4) + '" font-size="10" fill="#55636f">' + f.rr + '</text>';
    });
    svg += "</svg>";
    return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
  }

  function escapeXml(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function runPanel(text, outcomeArg, question, map) {
    var parsed = parseStudies(text, map, outcomeArg);
    if (!parsed.ok) return { ok: false, error: parsed.error };

    var ranked = rankFactors(parsed.studies);
    var vetted = ranked.map(function (r) {
      var flags = metaSkepticFlags(r);
      return Object.assign({}, r, { flags: flags, verdict: flags.length ? "flagged" : "solid", context: null });
    });

    var answer = focusedAnswer(question, vetted, parsed.outcome) || synthesize(vetted, parsed.outcome);
    var methods = "Risk ratios pooled per factor with DerSimonian-Laird random effects; " +
      "heterogeneity assessed with Cochran's Q and I²; factors with I² > 75%, fewer than three studies, " +
      "or a CI crossing 1 are flagged.";

    return {
      ok: true,
      data: {
        question: question,
        outcome: parsed.outcome,
        findings: vetted,
        vetted_answer: answer,
        safe_report: safeReportLine(vetted),
        debate: stubDebate(vetted, answer),
        refusal: null,
        figure: forestPlotSvg(parsed.outcome, vetted),
        caption: "Random-effects pooled risk ratios for " + parsed.outcome +
          ". Green = passes Skeptic checks; amber = flagged.",
        methods: methods,
        data_note: parsed.data_note,
        sources: parsed.studies.map(function (s) {
          return { study: s.population, factor: s.factor, rr: s.rr, ci_low: s.ci_low, ci_high: s.ci_high, n: s.n };
        }),
        narration: "local"
      },
      preview: parsed.studies.slice(0, 8)
    };
  }

  function statusSummary(text, map) {
    var headers = headersFromCsv(text);
    if (!headers.length) return { ok: false, msg: "Paste your table" };
    var m = map || suggestColumnMap(headers);
    var parsed = parseStudies(text, m);
    if (!parsed.ok) return { ok: false, msg: parsed.error };
    return {
      ok: true,
      msg: parsed.studies.length + " studies · " + parsed.factorCount + " factor" +
        (parsed.factorCount === 1 ? "" : "s"),
      preview: parsed.studies.slice(0, 8),
      map: m
    };
  }

  global.MetaClient = {
    headersFromCsv: headersFromCsv,
    suggestColumnMap: suggestColumnMap,
    mapOk: mapOk,
    parseStudies: parseStudies,
    runPanel: runPanel,
    statusSummary: statusSummary,
    safeReportLine: safeReportLine
  };
})(typeof window !== "undefined" ? window : globalThis);
