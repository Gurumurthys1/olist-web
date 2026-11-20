import { config } from './config'

// Calls our API Gateway with the Cognito token. Used from Phase 3 onwards.
async function call<T>(path: string, idToken: string, init: RequestInit = {}): Promise<T> {
  if (!config.apiUrl) throw new Error('The API is not connected yet (VITE_API_URL is empty).')
  const res = await fetch(`${config.apiUrl}${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${idToken}`, 'Content-Type': 'application/json', ...init.headers },
  })
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json() as Promise<T>
}

export const apiGet = <T>(path: string, idToken: string) => call<T>(path, idToken)

export const apiPost = <T>(path: string, body: unknown, idToken: string) =>
  call<T>(path, idToken, { method: 'POST', body: JSON.stringify(body) })
