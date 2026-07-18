export type Reading = {
  captured_at: string
  pm1: number | null
  pm25: number | null
  pm4: number | null
  pm10: number | null
  co2_ppm: number | null
  co2_warming: 0 | 1
  temp_c: number | null
  rh_pct: number | null
  // Present on aggregate tiers (1m, 1h); absent on raw (5s).
  pm25_min?: number | null
  pm25_max?: number | null
  co2_max?: number | null
  n?: number
}

export type Resolution = '5s' | '1m' | '1h'

export type ReadingsResponse = {
  resolution: Resolution
  bucket_seconds: number
  count: number
  readings: Reading[]
}

export async function fetchReadings(
  sinceIso: string,
  untilIso?: string,
): Promise<ReadingsResponse> {
  const url = new URL('/api/readings', window.location.origin)
  url.searchParams.set('since', sinceIso)
  if (untilIso) url.searchParams.set('until', untilIso)
  const res = await fetch(url)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return await res.json() as ReadingsResponse
}
