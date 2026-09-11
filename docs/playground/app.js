/*
 * The playground: this project's real engine, running in the reader's browser.
 *
 * Not a reimplementation and not a hosted service. Pyodide loads CPython as
 * WebAssembly, `micropip` installs the same wheel a `pip install` would, and
 * the analysis is the same `diff_services` and `evaluate_breaking` the CLI
 * calls. Nothing is uploaded: there is no server to upload it to.
 *
 * That matters for a contract. "Paste your API spec into our website" is a
 * request most people should refuse, and most playgrounds are asking exactly
 * that. This one cannot receive the text even if it wanted to.
 *
 * ## What this file is careful about
 *
 * **Saying what is happening.** A first load is tens of megabytes of
 * WebAssembly. A spinner with no words reads as broken, so every stage names
 * itself.
 *
 * **`deps=False`, and the failure it can cause.** The wheel declares `httpx`
 * and `flask`; the analysis path imports neither, and installing them would add
 * a dozen wheels to a first load for code this page cannot reach. The cost is
 * that a future import of something new fails at runtime rather than at
 * install, so an ImportError is caught and reported by module name.
 *
 * **Not blocking the page.** Pyodide is loaded on the first click, not on page
 * load: a docs page that pulls 30 MB because somebody scrolled past it is a
 * docs page that is slow for everybody.
 */

const OUT = document.getElementById('pg-output');
const STATUS = document.getElementById('pg-status');
const RUN = document.getElementById('pg-run');
const OLD = document.getElementById('pg-old');
const NEW = document.getElementById('pg-new');

let pyodide = null;
let loading = null;

const SAMPLE_OLD = `openapi: 3.0.3
info:
  title: Orders
  version: 1.2.0
paths:
  /orders:
    get:
      parameters:
        - name: limit
          in: query
          required: false
          schema: { type: integer, minimum: 1, maximum: 100 }
      responses:
        '200':
          description: ok
          content:
            application/json:
              schema:
                type: object
                required: [orders, total]
                properties:
                  orders: { type: array, items: { type: object } }
                  total: { type: integer }
  /orders/{id}:
    delete:
      parameters:
        - name: id
          in: path
          required: true
          schema: { type: string }
      responses:
        '204': { description: gone }
`;

const SAMPLE_NEW = `openapi: 3.0.3
info:
  title: Orders
  version: 2.0.0
paths:
  /orders:
    get:
      parameters:
        - name: limit
          in: query
          required: true
          schema: { type: integer, minimum: 10, maximum: 50 }
      responses:
        '200':
          description: ok
          content:
            application/json:
              schema:
                type: object
                required: [orders]
                properties:
                  orders: { type: array, items: { type: object } }
`;

function say(message, kind = 'info') {
  STATUS.textContent = message;
  STATUS.dataset.kind = kind;
}

/** The analysis, written once, in Python, calling the same functions the CLI
 * calls. Keeping it here rather than in a second module is deliberate: this is
 * the only Python the page has, and a reader checking that the playground runs
 * the real engine should be able to see all of it at once. */
const ANALYSIS = String.raw`
import json, tempfile, pathlib

def apiverity_compare(old_text, new_text):
    from apiverity.diff.engine import diff_services
    from apiverity.rules.breaking import evaluate_breaking
    from apiverity.security import run_security_checks
    from apiverity.specs.loader import detect_and_load

    with tempfile.TemporaryDirectory() as tmp:
        base = pathlib.Path(tmp)
        # Written out and read through the ordinary loader: one loader, one
        # model. A second path into the model is a second thing that can
        # disagree with the first.
        old_path = base / "old.yaml"
        new_path = base / "new.yaml"
        old_path.write_text(old_text, encoding="utf-8")
        new_path.write_text(new_text, encoding="utf-8")

        # Each side is loaded separately so a failure can say *which* pane is
        # the problem. A traceback is the wrong answer to a half-typed
        # contract: the reader knows they are mid-edit, and what they need is
        # the parser's complaint, not this project's call stack.
        loaded = {}
        for side, path in (("old", old_path), ("new", new_path)):
            try:
                loaded[side] = detect_and_load(str(path))
            except Exception as exc:
                return json.dumps({
                    "error": {
                        "side": side,
                        "type": type(exc).__name__,
                        "message": str(exc),
                    }
                })
        old, old_findings, plugin = loaded["old"]
        new, new_findings, _ = loaded["new"]

        changes = diff_services(old, new)
        breaking = evaluate_breaking(changes)
        security = run_security_checks(new)

    def row(f):
        return {
            "rule_id": f.rule_id,
            "severity": f.severity.value,
            "message": f.message,
            "operation": f.operation_key,
            "hint": f.hint,
        }

    return json.dumps({
        "protocol": plugin.protocol().value,
        "old_version": old.version,
        "new_version": new.version,
        "change_count": len(changes),
        "changes": [{"id": c.id, "kind": c.kind.value, "description": c.description} for c in changes],
        "breaking": [row(f) for f in breaking],
        "security": [row(f) for f in security + list(new_findings)],
    })
`;

async function boot() {
  const manifest = await (await fetch('manifest.json', { cache: 'no-store' })).json();

  say(`loading Python ${manifest.pyodide} (this is the slow part, once)`);
  const base = `https://cdn.jsdelivr.net/pyodide/v${manifest.pyodide}/full/`;
  await new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = `${base}pyodide.js`;
    script.onload = resolve;
    script.onerror = () => reject(new Error(`could not load ${script.src}`));
    document.head.appendChild(script);
  });

  const py = await globalThis.loadPyodide({ indexURL: base });

  say(`loading ${manifest.preload.join(', ')}`);
  await py.loadPackage(manifest.preload);

  const micropip = py.pyimport('micropip');
  if (manifest.install?.length) {
    say(`installing ${manifest.install.join(', ')}`);
    await micropip.install(manifest.install);
  }

  say(`installing api-verity-lab ${manifest.version}`);
  // `deps=False`: the wheel declares httpx and flask, and the analysis path
  // imports neither. See the note at the top of this file for what that costs.
  await micropip.install(new URL(manifest.wheel, document.baseURI).href, false, false);

  py.runPython(ANALYSIS);
  say(`ready — api-verity-lab ${manifest.version}, running in this tab`, 'ready');
  return py;
}

function escapeHtml(text) {
  return String(text).replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
  );
}

function renderFindings(title, findings, emptyNote) {
  if (!findings.length) {
    return `<h3>${title}</h3><p class="pg-empty">${emptyNote}</p>`;
  }
  const rows = findings
    .map(
      (f) => `<tr class="pg-sev-${f.severity.toLowerCase()}">
        <td><span class="pg-badge">${f.severity}</span></td>
        <td><code>${escapeHtml(f.rule_id)}</code></td>
        <td>${escapeHtml(f.message)}${f.hint ? `<br><em>${escapeHtml(f.hint)}</em>` : ''}</td>
      </tr>`,
    )
    .join('');
  return `<h3>${title} <span class="pg-count">${findings.length}</span></h3>
    <table class="pg-table"><tbody>${rows}</tbody></table>`;
}

function render(result) {
  const errors = result.breaking.filter((f) => f.severity === 'ERROR').length;
  const verdict =
    errors > 0
      ? `<p class="pg-verdict pg-bad">${errors} breaking change${errors === 1 ? '' : 's'}. This would fail a contract gate.</p>`
      : `<p class="pg-verdict pg-good">Nothing breaking. ${result.change_count} change${result.change_count === 1 ? '' : 's'} in total.</p>`;

  OUT.innerHTML = `
    ${verdict}
    <p class="pg-meta">${escapeHtml(result.protocol)} · ${escapeHtml(result.old_version)} →
      ${escapeHtml(result.new_version)} · ${result.change_count} change${result.change_count === 1 ? '' : 's'}</p>
    ${renderFindings('Breaking changes', result.breaking, 'No rule objected to this diff.')}
    ${renderFindings('Findings on the new contract', result.security, 'Nothing to report.')}
  `;
}

async function compare() {
  RUN.disabled = true;
  try {
    if (!pyodide) {
      loading ??= boot();
      pyodide = await loading;
    }
    say('running the rules');
    const fn = pyodide.globals.get('apiverity_compare');
    let raw;
    try {
      raw = fn(OLD.value, NEW.value);
    } finally {
      fn.destroy();
    }
    const result = JSON.parse(raw);
    if (result.error) {
      // The contract did not load. That is an answer, not a crash, and the
      // reader needs to know which pane and why.
      const side = result.error.side === 'old' ? 'old' : 'new';
      OUT.innerHTML = `<p class="pg-verdict pg-bad">The ${side} contract could not be read.</p>
        <pre class="pg-error">${escapeHtml(result.error.type)}: ${escapeHtml(result.error.message)}</pre>`;
      say(`the ${side} contract did not parse`, 'error');
      return;
    }
    render(result);
    say(`ready — api-verity-lab, running in this tab`, 'ready');
  } catch (error) {
    const message = String(error && error.message ? error.message : error);
    // An ImportError here is the `deps=False` trade coming due, and naming the
    // module is the difference between a bug report and a blank page.
    const missing = message.match(/No module named '([^']+)'/);
    OUT.innerHTML = `<pre class="pg-error">${escapeHtml(message)}</pre>`;
    say(
      missing
        ? `the analysis needs \`${missing[1]}\`, which this page does not install`
        : 'that did not work — the detail is below',
      'error',
    );
  } finally {
    RUN.disabled = false;
  }
}

document.getElementById('pg-sample')?.addEventListener('click', () => {
  OLD.value = SAMPLE_OLD;
  NEW.value = SAMPLE_NEW;
  say('sample loaded — press Compare');
});

RUN?.addEventListener('click', compare);

OLD.value = SAMPLE_OLD;
NEW.value = SAMPLE_NEW;
say('press Compare — Python loads on the first run, not on page load');
