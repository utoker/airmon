export type Reading = {
  id: string
  captured_at: string
  pm1: number | null
  pm25: number | null
  pm4: number | null
  pm10: number | null
  co2_ppm: number | null
  co2_warming: 0 | 1
  temp_c: number | null
  rh_pct: number | null
  received_at: string
}

export async function fetchReadings(sinceIso: string, limit = 5000): Promise<Reading[]> {
  const url = new URL('/api/readings', window.location.origin)
  url.searchParams.set('since', sinceIso)
  url.searchParams.set('limit', String(limit))
  const res = await fetch(url)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const body = await res.json()
  return body.readings as Reading[]
}
