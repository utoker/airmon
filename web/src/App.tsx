import { useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  LineChart, Line, XAxis, YAxis, Tooltip,
  CartesianGrid, ResponsiveContainer, Legend,
} from 'recharts'
import { fetchReadings, type Reading } from './api'

const RANGES = [
  { label: 'Last hour', hours: 1 },
  { label: 'Last 6h',   hours: 6 },
  { label: 'Last 24h',  hours: 24 },
  { label: 'Last 7d',   hours: 24 * 7 },
] as const

const REFRESH_MS = 5000

export function App() {
  const [rangeHours, setRangeHours] = useState<number>(1)
  const [readings, setReadings] = useState<Reading[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      try {
        const since = new Date(Date.now() - rangeHours * 3600_000).toISOString()
        const r = await fetchReadings(since)
        if (!cancelled) {
          setReadings(r.slice().reverse())
          setError(null)
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    const id = setInterval(load, REFRESH_MS)
    return () => { cancelled = true; clearInterval(id) }
  }, [rangeHours])

  const chartData = useMemo(() =>
    readings.map(r => ({
      tLabel: new Date(r.captured_at).toLocaleTimeString(),
      pm1: r.pm1, pm25: r.pm25, pm4: r.pm4, pm10: r.pm10,
      co2: r.co2_ppm,
      temp: r.temp_c, rh: r.rh_pct,
    }))
  , [readings])

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
          <span className="status">
            {loading ? '…' : `${readings.length} pts`}
            {error && <span className="error"> · {error}</span>}
          </span>
        </div>
      </header>

      {latest && (
        <section className="latest">
          <Metric label="PM2.5 (µg/m³)" value={latest.pm25} />
          <Metric label="CO₂ (ppm)" value={latest.co2_ppm}
                  warn={latest.co2_warming ? 'warming up' : undefined} />
          <Metric label="Temp (°C)" value={latest.temp_c} />
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
            <Line yAxisId="temp" dataKey="temp" name="Temp °C" dot={false} stroke="#e97a5b" isAnimationActive={false} />
            <Line yAxisId="rh"   dataKey="rh"   name="RH %"   dot={false} stroke="#5eaadf" isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </ChartCard>
    </div>
  )
}

function Metric({label, value, warn}: {label: string, value: number | null, warn?: string}) {
  return (
    <div className="metric">
      <div className="metric-label">{label}</div>
      <div className="metric-value">
        {value === null ? '—' : value.toFixed(1)}
      </div>
      {warn && <div className="metric-warn">{warn}</div>}
    </div>
  )
}

function ChartCard({title, children}: {title: string, children: ReactNode}) {
  return (
    <section className="card">
      <h2>{title}</h2>
      {children}
    </section>
  )
}
