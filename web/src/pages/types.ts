import type { DemoData } from '../data'
import type { useRoute } from '../router'

/** Props every page receives from the app shell. */
export type PageProps = { data: DemoData | null; route: ReturnType<typeof useRoute> }
