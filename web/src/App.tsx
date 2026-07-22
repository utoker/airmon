import { useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  LineChart, Line, XAxis, YAxis, Tooltip,
  CartesianGrid, ResponsiveContainer, Legend,
} from 'recharts'
import { fetchReadings, type Reading, type Resolution } from './api'

const RANGES = [
  { label: 'Last hour', hours: 1 },
  { label: 'Last 6h',   hours: 6 },
  { label: 'Last 24h',  hours: 24 },
  { label: 'Last 7d',   hours: 24 * 7 },
] as const

const RESOLUTION_LABEL: Record<Resolution, string> = {
  '5s': '5-second samples',
  '1m': 'per-minute averages',
  '1h': 'hourly averages',
}

const REFRESH_MS = 5000

export function App() {
  const [rangeHours, setRangeHours] = useState<number>(1)
  const [readings, setReadings] = useState<Reading[]>([])
  const [resolution, setResolution] = useState<Resolution>('5s')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    async function load({ showLoading }: { showLoading: boolean }) {
      if (showLoading) setLoading(true)
      try {
        const since = new Date(Date.now() - rangeHours * 3600_000).toISOString()
        const r = await fetchReadings(since)
        if (!cancelled) {
          setReadings(r.readings)
          setResolution(r.resolution)
          setError(null)
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      } finally {
        if (!cancelled && showLoading) setLoading(false)
      }
    }
    load({ showLoading: true })
    const id = setInterval(() => load({ showLoading: false }), REFRESH_MS)
    return () => { cancelled = true; clearInterval(id) }
  }, [rangeHours])

  const chartData = useMemo(() =>
    readings.map(r => ({
      tLabel: formatTick(r.captured_at, rangeHours),
      pm1: round2(r.pm1), pm25: round2(r.pm25), pm4: round2(r.pm4), pm10: round2(r.pm10),
      pm25_max: round2(r.pm25_max ?? null),
      co2: r.co2_ppm,
      temp: r.temp_c === null ? null : round2(cToF(r.temp_c)),
      rh: round2(r.rh_pct),
    }))
  , [readings, rangeHours])

  const latest = readings.at(-1)

  return (
    <div className="app">
      <header>
        <h1>airmon</h1>
        <div className="controls">
          {RANGES.map(r => (
            <button
              key={r.hours}
              onClick={() => setRangeHours(r.hours)}
              className={rangeHours === r.hours ? 'active' : ''}
            >{r.label}</button>
          ))}
          <span className="status" style={{opacity: loading ? 0.5 : 1}}>
            {readings.length
              ? `${readings.length} pts · ${RESOLUTION_LABEL[resolution]}`
              : loading ? 'loading…' : 'no data'}
            {error && <span className="error"> · {error}</span>}
          </span>
        </div>
      </header>

      {latest && (
        <section className="latest">
          <Metric label="PM2.5 (µg/m³)" value={latest.pm25}
                  band={pm25Band(latest.pm25)} />
          <Metric label="CO₂ (ppm)" value={latest.co2_ppm}
                  band={latest.co2_warming ? null : co2Band(latest.co2_ppm)}
                  warn={latest.co2_warming ? 'warming up' : undefined} />
          <Metric label="Temp (°F)" value={latest.temp_c === null ? null : cToF(latest.temp_c)} />
          <Metric label="Humidity (%)" value={latest.rh_pct} />
        </section>
      )}

      <ChartCard title="Particulate matter (µg/m³)">
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="tLabel" minTickGap={40} />
            <YAxis />
            <Tooltip />
            <Legend />
            <Line dataKey="pm1"  name="PM1"   dot={false} stroke="#8884d8" isAnimationActive={false} />
            <Line dataKey="pm25" name="PM2.5" dot={false} stroke="#82ca9d" isAnimationActive={false} />
            <Line dataKey="pm4"  name="PM4"   dot={false} stroke="#ffc658" isAnimationActive={false} />
            <Line dataKey="pm10" name="PM10"  dot={false} stroke="#ff7f7f" isAnimationActive={false} />
            {resolution !== '5s' && (
              <Line dataKey="pm25_max" name="PM2.5 max" dot={false}
                    stroke="#82ca9d" strokeDasharray="4 2" strokeOpacity={0.5}
                    isAnimationActive={false} />
            )}
          </LineChart>
        </ResponsiveContainer>
      </ChartCard>

      <ChartCard title="CO₂ (ppm)">
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="tLabel" minTickGap={40} />
            <YAxis domain={['auto', 'auto']} />
            <Tooltip />
            <Line dataKey="co2" name="CO₂" dot={false} stroke="#8884d8" isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </ChartCard>

      <ChartCard title="Temperature & humidity">
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="tLabel" minTickGap={40} />
            <YAxis yAxisId="temp" domain={['auto','auto']} />
            <YAxis yAxisId="rh" orientation="right" domain={[0,100]} />
            <Tooltip />
            <Legend />
            <Line yAxisId="temp" dataKey="temp" name="Temp °F" dot={false} stroke="#e97a5b" isAnimationActive={false} />
            <Line yAxisId="rh"   dataKey="rh"   name="RH %"   dot={false} stroke="#5eaadf" isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </ChartCard>

      <RangeReference />
    </div>
  )
}

type Band = { label: string, color: string }

function Metric({label, value, band, warn}: {
  label: string, value: number | null, band?: Band | null, warn?: string,
}) {
  return (
    <div className="metric">
      <div className="metric-label">{label}</div>
      <div className="metric-value">
        {value === null ? '—' : value.toFixed(1)}
      </div>
      {band && (
        <div className="metric-band" style={{background: band.color}}>
          {band.label}
        </div>
      )}
      {warn && <div className="metric-warn">{warn}</div>}
    </div>
  )
}

const cToF = (c: number) => c * 9 / 5 + 32

function round2(v: number | null): number | null {
  return v === null ? null : Math.round(v * 100) / 100
}

function formatTick(iso: string, rangeHours: number): string {
  const d = new Date(iso)
  if (rangeHours >= 24) {
    return d.toLocaleString(undefined, {
      month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
    })
  }
  return d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

const BANDS = {
  good:      '#2f9e44',
  moderate:  '#94c123',
  sensitive: '#f59f00',
  unhealthy: '#e8590c',
  veryBad:   '#c92a2a',
  hazardous: '#7c1d6f',
} as const

function pm25Band(v: number | null): Band | null {
  if (v === null) return null
  if (v < 9)   return { label: 'Good',                     color: BANDS.good }
  if (v < 35)  return { label: 'Moderate',                 color: BANDS.moderate }
  if (v < 55)  return { label: 'Unhealthy for sensitive',  color: BANDS.sensitive }
  if (v < 125) return { label: 'Unhealthy',                color: BANDS.unhealthy }
  if (v < 225) return { label: 'Very unhealthy',           color: BANDS.veryBad }
  return              { label: 'Hazardous',                color: BANDS.hazardous }
}

function co2Band(v: number | null): Band | null {
  if (v === null) return null
  if (v < 800)  return { label: 'Great',  color: BANDS.good }
  if (v < 1000) return { label: 'Fine',   color: BANDS.moderate }
  if (v < 1500) return { label: 'Stuffy', color: BANDS.sensitive }
  if (v < 2000) return { label: 'Poor',   color: BANDS.unhealthy }
  return               { label: 'Bad',    color: BANDS.veryBad }
}

function ChartCard({title, children}: {title: string, children: ReactNode}) {
  return (
    <section className="card">
      <h2>{title}</h2>
      {children}
    </section>
  )
}

type Row = { label: string, range: string, note: string, color: string }

const PM25_ROWS: Row[] = [
  { label: 'Good',                    range: '0 – 9',     note: 'WHO 2021 & EPA 2024 target', color: BANDS.good },
  { label: 'Moderate',                range: '9 – 35',    note: 'acceptable',                 color: BANDS.moderate },
  { label: 'Unhealthy for sensitive', range: '35 – 55',   note: 'kids, elderly, asthma',      color: BANDS.sensitive },
  { label: 'Unhealthy',               range: '55 – 125',  note: 'everyone',                   color: BANDS.unhealthy },
  { label: 'Very unhealthy',          range: '125 – 225', note: '',                           color: BANDS.veryBad },
  { label: 'Hazardous',               range: '225+',      note: '',                           color: BANDS.hazardous },
]

const CO2_ROWS: Row[] = [
  { label: 'Great',  range: '< 800',       note: 'outdoor ~420 ppm; fresh room', color: BANDS.good },
  { label: 'Fine',   range: '800 – 1000',  note: 'ASHRAE-comfort ceiling',       color: BANDS.moderate },
  { label: 'Stuffy', range: '1000 – 1500', note: 'measurable focus drop',        color: BANDS.sensitive },
  { label: 'Poor',   range: '1500 – 2000', note: 'headache, fatigue',            color: BANDS.unhealthy },
  { label: 'Bad',    range: '2000+',       note: 'ventilate now',                color: BANDS.veryBad },
]

function RangeTable({title, unit, rows}: {title: string, unit: string, rows: Row[]}) {
  return (
    <div className="range-table">
      <h3>{title} <span className="range-unit">({unit})</span></h3>
      <table>
        <tbody>
          {rows.map(r => (
            <tr key={r.label}>
              <td><span className="chip" style={{background: r.color}} /></td>
              <td className="band-name">{r.label}</td>
              <td className="range-cell">{r.range}</td>
              <td className="note">{r.note}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function RangeReference() {
  return (
    <details className="ranges">
      <summary>About the ranges</summary>
      <div className="ranges-body">
        <div>
          <RangeTable title="PM2.5" unit="µg/m³" rows={PM25_ROWS} />
          <p className="pm10-note">
            PM10 uses similar bands; WHO 24h guideline is 45 µg/m³.
          </p>
        </div>
        <RangeTable title="CO₂" unit="ppm" rows={CO2_ROWS} />
      </div>
      <p className="disclaimer">
        Thresholds are for 24-hour averages; short spikes on this dashboard don't constitute a health event.
      </p>
      <div className="sources">
        <span>Sources:</span>
        <a href="https://www.who.int/news/item/22-09-2021-new-who-global-air-quality-guidelines-aim-to-save-millions-of-lives-from-air-pollution"
           target="_blank" rel="noreferrer">WHO 2021 guidelines</a>
        <a href="https://www.iqair.com/us/support/knowledge-base/KA-05074-US"
           target="_blank" rel="noreferrer">EPA 2024 AQI update</a>
        <a href="https://www.ashrae.org/file%20library/about/position%20documents/pd-on-indoor-carbon-dioxide-english.pdf"
           target="_blank" rel="noreferrer">ASHRAE indoor CO₂ position</a>
        <a href="https://pmc.ncbi.nlm.nih.gov/articles/PMC4892924/"
           target="_blank" rel="noreferrer">Allen 2016 — CO₂ &amp; cognition</a>
      </div>
    </details>
  )
}
