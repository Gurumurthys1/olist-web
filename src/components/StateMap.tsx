import { CircleMarker, MapContainer, TileLayer, Tooltip } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'

// Capital city of each Brazilian state (same points as the QuickSight map)
const CAPITALS: Record<string, [number, number]> = {
  AC: [-9.97, -67.81], AL: [-9.65, -35.73], AP: [0.03, -51.07], AM: [-3.12, -60.02],
  BA: [-12.97, -38.5], CE: [-3.72, -38.54], DF: [-15.79, -47.88], ES: [-20.32, -40.34],
  GO: [-16.69, -49.25], MA: [-2.53, -44.3], MT: [-15.6, -56.1], MS: [-20.47, -54.62],
  MG: [-19.92, -43.94], PA: [-1.46, -48.5], PB: [-7.12, -34.86], PR: [-25.43, -49.27],
  PE: [-8.05, -34.88], PI: [-5.09, -42.8], RJ: [-22.91, -43.17], RN: [-5.79, -35.21],
  RS: [-30.03, -51.23], RO: [-8.76, -63.9], RR: [2.82, -60.67], SC: [-27.6, -48.55],
  SP: [-23.55, -46.63], SE: [-10.91, -37.07], TO: [-10.18, -48.33],
}

export type StateRow = { state: string; orders: number; revenue: number; late_pct: number | null }

export default function StateMap({ rows }: { rows: StateRow[] }) {
  const max = Math.max(1, ...rows.map((r) => r.orders))
  return (
    <MapContainer center={[-14.5, -52]} zoom={4} scrollWheelZoom={false} style={{ height: 320, borderRadius: 8 }}>
      <TileLayer
        attribution='&copy; OpenStreetMap contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      {rows.filter((r) => CAPITALS[r.state]).map((r) => (
        <CircleMarker
          key={r.state}
          center={CAPITALS[r.state]}
          radius={5 + 25 * Math.sqrt(r.orders / max)}
          pathOptions={{ color: '#a61e4d', fillColor: '#d6336c', fillOpacity: 0.55, weight: 1 }}
        >
          <Tooltip>
            <b>{r.state}</b><br />
            {r.orders.toLocaleString()} orders<br />
            R$ {Math.round(r.revenue).toLocaleString()}<br />
            {r.late_pct == null ? '' : `${(r.late_pct * 100).toFixed(1)}% late`}
          </Tooltip>
        </CircleMarker>
      ))}
    </MapContainer>
  )
}
