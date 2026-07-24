// 前端 API 客户端：封装咨询、历史、统计和知识库相关 HTTP 请求。
const API_BASE = import.meta.env.VITE_API_BASE ?? "";

async function request(path, options = {}) {
  const url = `${API_BASE}${path}`;
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options
  });
  if (!response.ok) {
    let detail = "";
    try {
      const payload = await response.json();
      detail = payload.detail ? `：${payload.detail}` : "";
    } catch {
      detail = "";
    }
    throw new Error(`${url} -> HTTP ${response.status}${detail}`);
  }
  if (response.status === 204) return null;
  return response.json();
}

export const api = {
  health: () => request("/api/system/health"),
  metrics: () => request("/api/system/metrics"),
  chat: ({ message, user_id = "demo_user", session_id = null }) =>
    request("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message, user_id, session_id })
    }),
  sessions: (user_id = "demo_user") => request(`/api/sessions?user_id=${encodeURIComponent(user_id)}&limit=30`),
  sessionDetail: (id, user_id = "demo_user") => request(`/api/sessions/${id}?user_id=${encodeURIComponent(user_id)}`),
  deleteSession: (id, user_id = "demo_user") => request(`/api/sessions/${id}?user_id=${encodeURIComponent(user_id)}`, { method: "DELETE" }),
  analyze: (question) =>
    request("/api/analyze", {
      method: "POST",
      body: JSON.stringify({ question })
    }),
  history: () => request("/api/history?limit=30"),
  historyDetail: (id) => request(`/api/history/${id}`),
  deleteHistory: (id) => request(`/api/history/${id}`, { method: "DELETE" })
};
