/* Deterministic meta-analysis panel — same math as askbench/clinical.py, runs in-browser. */
(function (global) {
  "use strict";

  // An odds ratio, a hazard ratio and a risk ratio are DIFFERENT quantities. They are
  // identical to code (all just a float in a column), which is exactly why lumping them
  // into one "rr" alias list silently reported a pooled odds ratio as "RR 2.035". The
  // pooling maths is the same for all three (log-transform, inverse-variance weight,
  // DerSimonian-Laird), so we accept them all, but we track WHICH measure it is and label
  // the output honestly. An OR overstates an RR whenever the outcome is common; an HR is a
  // rate over time and is not an RR at all. Reporting one as another is the exact class of
  // confident-but-wrong that this tool exists to refuse.
  var EFFECT_ALIASES = {
    RR: ["rr", "risk_ratio", "riskratio", "relative_risk"],
    OR: ["or", "odds_ratio", "oddsratio"],
    HR: ["hr", "hazard_ratio", "hazardratio"]
  };
  var LOG_EFFECT_ALIASES = {
    RR: ["log_rr", "logrr", "ln_rr"],
    OR: ["log_or", "logor", "ln_or"],
    HR: ["log_hr", "loghr", "ln_hr"]
  };

  // Label used when the table has no factor column (single-intervention meta-analysis).
  var SINGLE_FACTOR_LABEL = "intervention";

  var FIELD_ALIASES = {
    factor: ["factor", "risk_factor", "exposure", "treatment", "arm", "group", "intervention"],
    study: ["study", "population", "trial", "label", "cohort", "author", "reference", "paper"],
    n: ["n", "sample_size", "total", "participants", "patients"],
    outcome: ["outcome", "endpoint"],
    log_rr: ["log_rr", "logrr", "ln_rr", "log_or", "log_hr"],
    se: ["se", "stderr", "standard_error", "sem"],
    rr: ["rr", "risk_ratio", "or", "odds_ratio", "hr", "hazard_ratio", "effect"],
    ci_low: ["ci_low", "ci_lower", "lower", "lcl", "lower_ci", "lo_95", "ci_lo"],
    ci_high: ["ci_high", "ci_upper", "upper", "ucl", "upper_ci", "hi_95", "ci_hi"],
    // Raw 2x2 counts: the most common real format, and what Colditz/dat.bcg actually is.
    // Requiring a pre-computed log_rr+se meant the user had to write code first, which
    // contradicts the whole "no code required" promise.
    // Aliases cover both word orders a scientist naturally writes: "events_treated"
    // and "treated_events", "total_control" and "control_total". A real paste should
    // map without the user renaming columns first.
    events_treat: ["events_treat", "events_treated", "treated_events", "treatment_events", "tpos", "a", "e_treat", "event_exposed", "events_exposed", "exposed_events", "cases_treat"],
    total_treat: ["total_treat", "total_treated", "treated_total", "treatment_total", "n_treat", "n_treated", "treated_n", "treatment_n", "n1", "n_exposed", "exposed_total", "exposed_n"],
    events_ctrl: ["events_ctrl", "events_control", "control_events", "ctrl_events", "comparison_events", "cpos", "c", "e_ctrl", "event_control", "events_unexposed", "unexposed_events", "cases_ctrl"],
    total_ctrl: ["total_ctrl", "total_control", "control_total", "ctrl_total", "comparison_total", "n_ctrl", "n_control", "control_n", "ctrl_n", "n0", "n_unexposed", "unexposed_total", "unexposed_n"],
    // metafor's dat.bcg column names: tpos/tneg/cpos/cneg (negatives, not totals)
    nonevents_treat: ["tneg", "nonevents_treat", "nonevents_treated", "treated_nonevents", "noncases_treat"],
    nonevents_ctrl: ["cneg", "nonevents_ctrl", "nonevents_control", "control_nonevents", "noncases_ctrl"]
  };

  // Which effect measure does this table report? Returns "RR" | "OR" | "HR" | "" (unknown).
  function detectEffectMeasure(headers) {
    var norms = headers.map(normHeader);
    var m, i;
    for (m in LOG_EFFECT_ALIASES) {
      for (i = 0; i < norms.length; i++) {
        if (LOG_EFFECT_ALIASES[m].indexOf(norms[i]) !== -1) return m;
      }
    }
    for (m in EFFECT_ALIASES) {
      for (i = 0; i < norms.length; i++) {
        if (EFFECT_ALIASES[m].indexOf(norms[i]) !== -1) return m;
      }
    }
    return "";
  }

  function normHeader(h) {
    return String(h || "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
  }

  // A scientist's table lives in Excel or Sheets, and pasting from there gives TABS, not
  // commas. Splitting on commas only meant the most common paste in the world arrived as
  // a single column and failed with a message about column schemas, which is the opposite
  // of "no code required". Sniff the delimiter from the header line instead.
  function sniffDelimiter(text) {
    var header = String(text || "").split(/\r?\n/)[0] || "";
    var best = ",", bestCount = 0;
    [",", "\t", ";", "|"].forEach(function (d) {
      var n = header.split(d).length - 1;
      if (n > bestCount) { bestCount = n; best = d; }
    });
    return bestCount > 0 ? best : ",";
  }

  function parseCsvRows(text, delim) {
    delim = delim || sniffDelimiter(text);
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
      else if (c === delim) { row.push(cell); cell = ""; }
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
    // Every role here must also exist in FIELD_ALIASES: the loop below only fills keys
    // present in this object, so a role missing here is silently never detected.
    var map = {
      factor: "", study: "", n: "", outcome: "", log_rr: "", se: "", rr: "", ci_low: "", ci_high: "",
      events_treat: "", total_treat: "", events_ctrl: "", total_ctrl: "",
      nonevents_treat: "", nonevents_ctrl: ""
    };
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

  // Raw 2x2 counts are usable if we have events + group size on both arms. Group size can
  // come either as a total (n_treat) or as the negatives (tneg), which is metafor's shape.
  function twoByTwoOk(map) {
    var treatSize = map.total_treat || map.nonevents_treat;
    var ctrlSize = map.total_ctrl || map.nonevents_ctrl;
    return !!(map.events_treat && treatSize && map.events_ctrl && ctrlSize);
  }

  // A single-intervention meta-analysis is the most common real table there is: one
  // treatment, many trials, and therefore NO factor column, because there is only one
  // factor. Hard-requiring `factor` rejected exactly the tables this tab exists to
  // accept, including metafor's dat.bcg (study,tpos,tneg,cpos,cneg), i.e. the real
  // published data our own demo is built on. A missing factor column is not a mapping
  // error; it means every row shares one factor (see SINGLE_FACTOR_LABEL below).
  function mapOk(map) {
    if (!map) return false;
    if (map.log_rr && map.se) return true;
    if (map.rr && map.se) return true;
    if (map.rr && map.ci_low && map.ci_high) return true;
    if (twoByTwoOk(map)) return true;
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
    if (!mapOk(map)) {
      return { ok: false, error: "Map columns: need one of: raw 2x2 counts " +
        "(events and size for each arm), an effect with its SE, or an effect with both CI bounds." };
    }

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
    // Raw 2x2 counts (events + arm size on each arm).
    var eti = colIndex(headers, map.events_treat);
    var tti = colIndex(headers, map.total_treat);
    var eci = colIndex(headers, map.events_ctrl);
    var tci = colIndex(headers, map.total_ctrl);
    var nti = colIndex(headers, map.nonevents_treat);
    var nci = colIndex(headers, map.nonevents_ctrl);

    var studies = [];
    var seenOutcome = null;
    for (var r = 1; r < rows.length; r++) {
      var cells = rows[r];
      // No factor column at all: a single-intervention meta-analysis, so every row shares
      // one factor. (A factor column that exists but is blank on this row is still bad
      // data, and that row is still skipped.)
      var factor = fi >= 0 ? String(cells[fi] || "").trim() : SINGLE_FACTOR_LABEL;
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

      // Raw 2x2 counts -> log risk ratio + SE. Identical to askbench/clinical.py
      // (make_bcg_meta): rr = (a/n1)/(c/n0), se = sqrt(1/a - 1/n1 + 1/c - 1/n0). This is
      // the risk-ratio variance, not the odds-ratio one. Arm size may be given as a total
      // (n_treat) or as negatives (tneg), which is metafor's dat.bcg shape.
      if (logRr == null && eti >= 0) {
        var a = fnum(cells[eti]);
        var c = eci >= 0 ? fnum(cells[eci]) : null;
        var n1 = tti >= 0 ? fnum(cells[tti])
               : (nti >= 0 && a != null ? a + fnum(cells[nti]) : null);
        var n0 = tci >= 0 ? fnum(cells[tci])
               : (nci >= 0 && c != null ? c + fnum(cells[nci]) : null);
        if (a != null && c != null && n1 > 0 && n0 > 0 && a <= n1 && c <= n0) {
          // Haldane-Anscombe: a zero cell leaves the ratio and its variance undefined, so
          // add 0.5 to every cell. Standard practice and what metafor does by default.
          if (a === 0 || c === 0 || a === n1 || c === n0) { a += 0.5; c += 0.5; n1 += 1; n0 += 1; }
          var riskT = a / n1, riskC = c / n0;
          if (riskT > 0 && riskC > 0) {
            logRr = Math.log(riskT / riskC);
            se = Math.sqrt(1 / a - 1 / n1 + 1 / c - 1 / n0);
            if (!(nVal > 0)) n = Math.round(n1 + n0);
          }
        }
      }

      // NEVER invent uncertainty. There used to be a `se = 0.2` fallback here for a row
      // that gave an effect with no SE and no CI. A constant SE makes every weight
      // identical, so Q has nothing to detect, I2 collapses to 0 and the heterogeneity
      // gate always opens: a table carrying zero uncertainty came back SOLID with a
      // confident 95% CI. That interval was fabricated, and it disarmed the one check
      // this tool exists to perform. A row without uncertainty is not poolable.
      if (logRr != null && (se == null || se <= 0)) {
        return { ok: false, error: "Row " + r + " (" + factor + "): an effect with no uncertainty " +
          "cannot be pooled. Add a standard error, or both confidence limits, or the raw 2x2 " +
          "counts. We will not invent the uncertainty for you." };
      }

      if (logRr == null || se == null || se <= 0) {
        return { ok: false, error: "Row " + r + " (" + factor + "): need raw 2x2 counts " +
          "(events and size per arm), an effect with its SE, or an effect with both CI bounds." };
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
    // Which quantity did the user actually give us? 2x2 counts are a risk ratio by
    // construction; otherwise the column header decides. Never assume RR.
    var measure = twoByTwoOk(map) && !map.log_rr && !map.rr
      ? "RR" : (detectEffectMeasure(headers) || "RR");

    return {
      ok: true,
      studies: studies,
      outcome: outcome,
      effect_measure: measure,
      factorCount: Object.keys(factors).length,
      // The OR/HR warning must live HERE, not only in `methods`: methods renders inside the
      // collapsed forest-plot section, so the single most important caveat (this is not a
      // risk ratio) was one click from invisible. Caveats go up front, not buried.
      data_note: "Your pasted table (" + studies.length + " study rows, " +
        Object.keys(factors).length + " factor(s)). Outcome: " + outcome +
        ". Computed locally in your browser — same toolkit math as the server." +
        (measure !== "RR"
          ? " Your table reports " + measure + ", so every pooled figure here is an " +
            measure + ", not a risk ratio: they are different quantities and are not interchangeable."
          : "")
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

  // `m` is the effect measure actually reported by the table (RR/OR/HR). Naming it in the
  // flag text matters: "CI crosses no-effect (OR 0.8 to 1.3)" is true, the same sentence
  // with RR is not, and an OR overstates an RR whenever the outcome is common.
  function metaSkepticFlags(row, maxI2, minStudies, m) {
    m = m || "RR";
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
      flags.push("confidence interval crosses no-effect (" + m + " " + row.ci_low + " to " + row.ci_high + "); not significant");
    } else if (row.rr >= 0.9 && row.rr <= 1.11) {
      flags.push("effect is clinically negligible (pooled " + m + " " + row.rr + " sits inside the null band 0.90 to 1.11)");
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

  function focusedAnswer(question, vetted, outcome, m) {
    m = m || "RR";
    var q = String(question || "").toLowerCase();
    var het = vetted.filter(function (v) {
      return v.verdict === "flagged" && (v.flags || []).some(function (f) { return /heterogen/i.test(f); });
    });
    var solid = vetted.filter(function (v) { return v.verdict === "solid"; });

    if (/heterogen|pool|trustworthy|one number|safe|report/.test(q) && het.length) {
      var h = het[0];
      return "Safe to report one pooled number for " + h.factor + ": No. I²=" + h.i2 +
        "% is too high. Pooling would hide disagreement across studies, not resolve it.";
    }
    if (/strongest|effect|largest/.test(q) && vetted.length) {
      var top = vetted[0];
      var tag = top.verdict === "solid" ? "passes" : "does not pass";
      return "Strongest pooled effect on " + outcome + ": " + top.factor + " (" + m + " " + top.rr +
        ", 95% CI " + top.ci_low + " to " + top.ci_high + ", I²=" + top.i2 + "%) — " +
        tag + " the Skeptic's checks.";
    }
    if (solid.length) {
      var names = solid.map(function (v) {
        return v.factor + " (" + m + " " + v.rr + ", " + v.k + " studies)";
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

  function synthesize(vetted, outcome, m) {
    return focusedAnswer("", vetted, outcome, m);
  }

  function safeReportLine(vetted) {
    var solid = vetted.filter(function (v) { return v.verdict === "solid"; });
    if (solid.length) {
      return "Safe to report one pooled number for " + solid[0].factor + ": Yes. Passes study count, heterogeneity, and significance checks.";
    }
    var flagged = vetted.filter(function (v) { return v.verdict === "flagged"; });
    if (!flagged.length) return "";
    var h = flagged[0];
    if ((h.flags || []).some(function (f) { return /heterogen/i.test(f); })) {
      return "Safe to report one pooled number for " + h.factor + ": No. I²=" + h.i2 + "% (too heterogeneous).";
    }
    return "Safe to report one pooled number for " + h.factor + ": No. " + ((h.flags || [])[0] || "checks failed");
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

    // The effect measure the table actually reports (RR/OR/HR). Declared before first use:
    // the flags and the answer sentence both name it, and naming it wrong is the exact
    // confident-but-wrong this tool refuses.
    var measure = parsed.effect_measure || "RR";

    var ranked = rankFactors(parsed.studies);
    var vetted = ranked.map(function (r) {
      var flags = metaSkepticFlags(r, undefined, undefined, measure);
      return Object.assign({}, r, { flags: flags, verdict: flags.length ? "flagged" : "solid", context: null });
    });

    var answer = focusedAnswer(question, vetted, parsed.outcome, measure) || synthesize(vetted, parsed.outcome, measure);
    var MEASURE_NAME = { RR: "Risk ratios", OR: "Odds ratios", HR: "Hazard ratios" };
    var methods = (MEASURE_NAME[measure] || "Risk ratios") + " pooled per factor with DerSimonian-Laird " +
      "random effects; heterogeneity assessed with Cochran's Q and I²; factors with I² > 75%, " +
      "fewer than three studies, or a CI crossing 1 are flagged." +
      (measure !== "RR"
        ? " Your table reports " + measure + ", so every pooled figure here is an " + measure +
          ", not a risk ratio: they are different quantities and are not interchangeable."
        : "");

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
        effect_measure: measure,
        figure: forestPlotSvg(parsed.outcome, vetted),
        caption: "Random-effects pooled " + (measure === "RR" ? "risk ratios" : measure === "OR" ? "odds ratios" : "hazard ratios") +
          " for " + parsed.outcome + ". Green = passes Skeptic checks; amber = flagged.",
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
