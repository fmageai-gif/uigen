/**
 * Case Clicker — opens the next unopened case in the Dynamics 365 grid.
 *
 * Runs inside the Dynamics tab. Each run opens exactly one case: the topmost
 * row whose case ID has not been opened before, then stops.
 *
 * Rows are located by the 10-digit case ID in their text rather than by CSS
 * class, so a Dynamics UI update does not break it. The opened list lives in
 * localStorage on the Dynamics origin, so it survives reloads and restarts.
 *
 * Console commands once loaded:
 *   caseClicker.next()    open the next unopened case
 *   caseClicker.list()    show opened IDs and what is visible now
 *   caseClicker.undo()    release the most recently opened ID
 *   caseClicker.reset()   clear the whole opened list
 *   caseClicker.scan()    dump page structure (for debugging)
 */
(function () {
  "use strict";

  var STORE_KEY = "caseClicker.opened";
  var CASE_ID_RE = /\b\d{10}\b/;

  function loadOpened() {
    try {
      return JSON.parse(localStorage.getItem(STORE_KEY) || "[]");
    } catch (e) {
      return [];
    }
  }

  function saveOpened(list) {
    localStorage.setItem(STORE_KEY, JSON.stringify(list));
  }

  /** Top document plus every same-origin iframe; Dynamics nests its grid. */
  function allDocs() {
    var docs = [];
    function walk(win) {
      var doc = null;
      try {
        doc = win.document;
      } catch (e) {
        return; // cross-origin frame, skip
      }
      if (!doc || docs.indexOf(doc) !== -1) return;
      docs.push(doc);
      var frames = win.frames;
      for (var i = 0; i < frames.length; i++) {
        try {
          walk(frames[i]);
        } catch (e) {
          /* cross-origin */
        }
      }
    }
    walk(window.top || window);
    return docs;
  }

  /** Every grid row that carries a case ID, in visual order. */
  function findRows() {
    var found = [];
    var seen = {};
    var docs = allDocs();

    for (var d = 0; d < docs.length; d++) {
      var rows = docs[d].querySelectorAll('[role="row"], tr');
      for (var r = 0; r < rows.length; r++) {
        var row = rows[r];
        var text = row.innerText || row.textContent || "";
        var m = text.match(CASE_ID_RE);
        if (!m) continue;
        if (seen[m[0]]) continue;
        // Skip rows with no layout box (hidden / virtualised off-screen).
        if (!row.getClientRects().length) continue;
        seen[m[0]] = true;
        found.push({ caseId: m[0], row: row, text: text });
      }
    }
    return found;
  }

  /** The element that actually opens the record when clicked. */
  function clickTarget(row) {
    var link = row.querySelector('a[href], a[role="link"], [role="link"]');
    if (link) return link;
    var cells = row.querySelectorAll('[role="gridcell"], td');
    // First cell is usually a checkbox; the second holds the subject link.
    for (var i = 0; i < cells.length; i++) {
      var t = (cells[i].innerText || "").trim();
      if (t && !/^\s*$/.test(t)) return cells[i];
    }
    return row;
  }

  function realClick(el) {
    try {
      el.scrollIntoView({ block: "center", inline: "nearest" });
    } catch (e) {
      /* older engines */
    }
    var win = el.ownerDocument.defaultView || window;
    var opts = { bubbles: true, cancelable: true, view: win, button: 0 };
    // Pointer/mouse sequence first, for handlers that track press-and-release.
    // The click itself is delivered exactly once, below — dispatching a
    // 'click' event here as well would open the record twice.
    ["pointerdown", "mousedown", "pointerup", "mouseup"].forEach(function (type) {
      var Ctor =
        win.PointerEvent && type.indexOf("pointer") === 0
          ? win.PointerEvent
          : win.MouseEvent;
      try {
        el.dispatchEvent(new Ctor(type, opts));
      } catch (e) {
        /* ignore unsupported event type */
      }
    });
    if (typeof el.click === "function") {
      el.click();
    } else {
      el.dispatchEvent(new win.MouseEvent("click", opts));
    }
  }

  function toast(message, isError) {
    var docs = allDocs();
    var doc = docs[0] || document;
    var el = doc.createElement("div");
    el.textContent = message;
    el.style.cssText = [
      "position:fixed",
      "z-index:2147483647",
      "top:16px",
      "left:50%",
      "transform:translateX(-50%)",
      "padding:10px 16px",
      "border-radius:8px",
      "font:600 13px system-ui,sans-serif",
      "color:#fff",
      "box-shadow:0 4px 14px rgba(0,0,0,.3)",
      "background:" + (isError ? "#b91c1c" : "#047857"),
    ].join(";");
    doc.body.appendChild(el);
    setTimeout(function () {
      if (el.parentNode) el.parentNode.removeChild(el);
    }, 4000);
  }

  function scan() {
    var docs = allDocs();
    console.log("=== Case Clicker scan ===");
    console.log("Documents reachable:", docs.length);
    for (var i = 0; i < docs.length; i++) {
      var doc = docs[i];
      console.log(
        "  [" + i + "]",
        doc.location ? doc.location.href.slice(0, 120) : "(no location)",
        "| role=row:",
        doc.querySelectorAll('[role="row"]').length,
        "| tr:",
        doc.querySelectorAll("tr").length,
        "| role=grid:",
        doc.querySelectorAll('[role="grid"]').length
      );
    }
    var rows = findRows();
    console.log("Rows carrying a 10-digit case ID:", rows.length);
    if (rows.length) {
      console.log("First row HTML sample:");
      console.log(rows[0].row.outerHTML.slice(0, 1500));
    }
    return rows.length;
  }

  function next() {
    var opened = loadOpened();
    var rows = findRows();

    if (!rows.length) {
      toast("No case rows found — see console (F12)", true);
      console.warn(
        "Case Clicker could not find any grid rows containing a 10-digit case ID."
      );
      scan();
      return null;
    }

    var target = null;
    for (var i = 0; i < rows.length; i++) {
      if (opened.indexOf(rows[i].caseId) === -1) {
        target = rows[i];
        break;
      }
    }

    if (!target) {
      toast(
        "All " + rows.length + " visible cases already opened — scroll for more",
        true
      );
      console.log("Opened so far (" + opened.length + "):", opened.join(", "));
      return null;
    }

    // Recorded before the click, because opening the case navigates away and
    // stops this script mid-run. Use caseClicker.undo() if a click misfires.
    opened.push(target.caseId);
    saveOpened(opened);

    toast("Opening case " + target.caseId + "  (#" + opened.length + ")");
    console.log("Case Clicker → opening", target.caseId);
    realClick(clickTarget(target.row));
    return target.caseId;
  }

  function list() {
    var opened = loadOpened();
    var rows = findRows();
    console.log("=== Case Clicker ===");
    console.log("Opened (" + opened.length + "):", opened.join(", ") || "(none)");
    var remaining = rows.filter(function (r) {
      return opened.indexOf(r.caseId) === -1;
    });
    console.log(
      "Visible now: " + rows.length + " rows, " + remaining.length + " unopened"
    );
    console.log(
      "Next up:",
      remaining.length ? remaining[0].caseId : "(none visible)"
    );
    return { opened: opened, visible: rows.length, remaining: remaining.length };
  }

  function undo() {
    var opened = loadOpened();
    var removed = opened.pop();
    saveOpened(opened);
    console.log("Released:", removed || "(nothing to release)");
    toast(removed ? "Released " + removed : "Nothing to release", !removed);
    return removed;
  }

  function reset() {
    saveOpened([]);
    console.log("Opened list cleared.");
    toast("Opened list cleared");
  }

  window.caseClicker = {
    next: next,
    list: list,
    undo: undo,
    reset: reset,
    scan: scan,
  };

  // Running the bookmarklet opens the next case immediately.
  next();
})();
