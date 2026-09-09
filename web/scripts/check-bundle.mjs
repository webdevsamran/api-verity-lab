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
 * Raised once, from 210,000, when the agent-governance page group took the
 * entry to 205.7 kB and left 4 kB of room -- less than one feature. The plan
 * that called for this raise proposed 260,000, and that number would have
 * been a mistake: an un-split build of this app is around 240 kB, so a
 * 260,000 budget would pass the exact failure the check exists to catch. The
 * assertion below now derives that ceiling from the build itself rather than
 * trusting either number. */
const ENTRY_BUDGET_BYTES = 220_000

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
