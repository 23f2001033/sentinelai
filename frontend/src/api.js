const BASE = import.meta.env.VITE_API_BASE ?? ''

async function request(path, options = {}) {
  const response = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* response had no JSON body */
    }
    throw new Error(detail)
  }
  return response.status === 204 ? null : response.json()
}

export const api = {
  health: () => request('/api/health'),
  stats: () => request('/api/stats'),

  listPolicies: () => request('/api/policies'),
  getPolicy: (id) => request(`/api/policies/${id}`),
  simulate: (id, payload) =>
    request(`/api/policies/${id}/simulate`, { method: 'POST', body: JSON.stringify(payload) }),

  listAgents: () => request('/api/agents'),

  listRuns: () => request('/api/runs'),
  getRun: (id) => request(`/api/runs/${id}`),
  getRunAudit: (id) => request(`/api/runs/${id}/audit`),
  createRun: (payload) => request('/api/runs', { method: 'POST', body: JSON.stringify(payload) }),
  cancelRun: (id) => request(`/api/runs/${id}/cancel`, { method: 'POST' }),

  listApprovals: (status) =>
    request(`/api/approvals${status ? `?status_filter=${status}` : ''}`),
  decideApproval: (id, payload) =>
    request(`/api/approvals/${id}/decide`, { method: 'POST', body: JSON.stringify(payload) }),

  spendSummary: () => request('/api/spend/summary'),
}

export function socketUrl(path) {
  if (BASE) return BASE.replace(/^http/, 'ws') + path
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}${path}`
}
