/* Bundle budget for the demo app.
 *
 * The point is not to police kilobytes -- it is that the code splitting in
 * `src/pages/index.tsx` is invisible when it breaks. One static import of a
 * page module from the shell collapses every chunk back into the entry file,
 * the app still builds, still passes every test, and still renders. Only the
 * download gets worse. So the check that matters is structural: the page
 * groups must still be separate files.
 *
 * Run after `npm run build`.
 */
import { readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

const ASSETS = join(process.cwd(), 'dist', 'assets')
const GROUPS = ['overview', 'contract', 'testing', 'runtime', 'agents', 'team']
/* Headroom over the measured entry chunk: enough that ordinary feature work
 * does not trip it, tight enough that an un-split build does.
 *
 * Raised from 210,000 to 220,000 when the agent-governance page group took the
 * entry to 205.7 kB and left 4 kB of room -- less than one feature. The plan
 * behind that raise proposed 260,000, and at the time that would have been a
 * mistake: an un-split build then weighed about 240 kB, so a 260,000 budget
 * would have passed the exact failure this check exists to catch.
 *
 * Raised again to 260,000 for React 19.3.0, which added 29,273 B to the entry
 * on its own (214,558 -> 243,831 B) with no source change. The number that was
 * wrong before is right now, and only because the app grew: the assertion
 * below derives the un-split weight from the build rather than from memory,
 * and it is 301,858 B. So 260,000 still sits 42 kB under the point where this
 * check would stop being able to tell a split build from an un-split one, and
 * leaves ~16 kB for ordinary work.
 *
 * That derived assertion is the one that matters. If a future raise pushes
 * this constant up to meet it, the answer is not a bigger number -- it is that
 * the shell has started carrying page code. */
const ENTRY_BUDGET_BYTES = 260_000

let files
try {
  files = readdirSync(ASSETS).filter((f) => f.endsWith('.js'))
} catch {
  console.error(`no build output at ${ASSETS} -- run 'npm run build' first`)
  process.exit(1)
}

const size = (f) => statSync(join(ASSETS, f)).size
const entry = files.find((f) => f.startsWith('index-'))
const problems = []

if (!entry) {
  problems.push('no entry chunk (index-*.js) in the build output')
} else if (size(entry) > ENTRY_BUDGET_BYTES) {
  problems.push(
    `entry chunk is ${size(entry).toLocaleString()} B, over the ` +
      `${ENTRY_BUDGET_BYTES.toLocaleString()} B budget. If page code got ` +
      `pulled in, look for a static import of ./pages/* outside index.tsx.`,
  )
}

for (const group of GROUPS) {
  if (!files.some((f) => f.startsWith(`${group}-`))) {
    problems.push(
      `'${group}' is not a separate chunk -- something imports it statically, ` +
        `so it now ships to every visitor`,
    )
  }
}

/* The budget has to stay under what an un-split build would weigh, or it
 * stops being able to detect one. Checked against this build rather than
 * against a remembered figure, because the remembered figure is what goes
 * stale. */
const unsplit = entry ? size(entry) + files.filter((f) => f !== entry).reduce((n, f) => n + size(f), 0) : 0
if (unsplit && ENTRY_BUDGET_BYTES >= unsplit) {
  problems.push(
    `the budget (${ENTRY_BUDGET_BYTES.toLocaleString()} B) is at or above what an ` +
      `un-split build would weigh (${unsplit.toLocaleString()} B), so it can no longer ` +
      `detect the failure it exists for. Lower it.`,
  )
}

const report = files
  .map((f) => `  ${String(size(f)).padStart(8)} B  ${f}`)
  .sort()
  .join('\n')

if (problems.length) {
  console.error('Bundle budget failed:\n' + problems.map((p) => `  - ${p}`).join('\n'))
  console.error('\nBuilt chunks:\n' + report)
  process.exit(1)
}

console.log(
  `Bundle budget ok — entry ${size(entry).toLocaleString()} B, ` +
    `${GROUPS.length} page chunks split out.`,
)
console.log(report)
