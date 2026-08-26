import { useEffect, useState } from 'react'

export interface Route {
  page: string
  params: URLSearchParams
}

function parseHash(): Route {
  const raw = window.location.hash.replace(/^#\/?/, '')
  const [path, query = ''] = raw.split('?')
  return { page: path || 'home', params: new URLSearchParams(query) }
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(parseHash)
  useEffect(() => {
    const onChange = () => setRoute(parseHash())
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return route
}

export function navigate(page: string, params?: Record<string, string>) {
  const qs = params && Object.keys(params).length
    ? '?' + new URLSearchParams(params).toString()
    : ''
  window.location.hash = `/${page}${qs}`
}

export function setParam(route: Route, key: string, value: string) {
  const next = new URLSearchParams(route.params.toString())
  if (value) next.set(key, value)
  else next.delete(key)
  window.location.hash = `/${route.page}?${next.toString()}`
}