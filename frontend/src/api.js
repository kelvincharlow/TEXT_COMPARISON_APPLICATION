const API_BASE = "/api/v1";

async function request(path, options = {}) {
  const response = await fetch(path.startsWith("/api/") ? path : `${API_BASE}${path}`, {
    ...options,
    credentials: "same-origin",
    cache: "no-store",
    headers: { "X-Postbank-Request": "1", ...options.headers },
  });
  if (!response.ok) {
    let message = "The request could not be completed.";
    try {
      const body = await response.json();
      message = typeof body.detail === "string" ? body.detail : "Check the required fields and try again.";
    } catch { /* Keep the fallback for non-JSON errors. */ }
    const error = new Error(message);
    error.status = response.status;
    if (response.status === 401) window.dispatchEvent(new Event("postbank-session-expired"));
    throw error;
  }
  return response;
}

export async function login(email, password) {
  return (await request("/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password }) })).json();
}
export async function currentUser() { return (await request("/auth/me")).json(); }
export async function logout() { await request("/auth/logout", { method: "POST" }); }
export async function departments() { return (await request("/departments")).json(); }
export async function comparisonHistory(offset = 0) { return (await request(`/comparisons?offset=${offset}`)).json(); }
export async function getComparison(id) { return (await request(`/comparisons/${id}`)).json(); }

export async function compareDocuments(original, revised, metadata) {
  const formData = new FormData();
  formData.append("original", original);
  formData.append("revised", revised);
  for (const [key, value] of Object.entries(metadata)) formData.append(key, value);
  return (await request("/compare", { method: "POST", body: formData })).json();
}
export async function downloadRedline(url) { return (await request(url)).blob(); }

export async function reviewQueue(offset = 0) { return (await request(`/review-tasks?offset=${offset}`)).json(); }
export async function reviewAction(taskId, action, body = {}) {
  return (await request(`/review-tasks/${taskId}/${action}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  })).json();
}

export async function eligibleReviewers(taskId) { return (await request(`/review-tasks/${taskId}/eligible-reviewers`)).json(); }

export async function notifications(offset = 0) { return (await request(`/notifications?offset=${offset}`)).json(); }
export async function markNotificationRead(id) { await request(`/notifications/${id}/read`, { method: "POST" }); }
export async function uploadRevision(comparisonId, reviewRevision, file) {
  const formData = new FormData();
  formData.append("review_revision", reviewRevision);
  formData.append("revised", file);
  return (await request(`/comparisons/${comparisonId}/revisions`, { method: "POST", body: formData })).json();
}

export async function preparePreview(id) { return (await request(`/comparisons/${id}/preview`, { method: "POST" })).json(); }
export async function issueRecipients(taskId) { return (await request(`/review-tasks/${taskId}/issue-recipients`)).json(); }
export async function issueInbox(offset = 0) { return (await request(`/review-issues?offset=${offset}`)).json(); }
export async function adminSettings() { return (await request('/admin/settings')).json(); }
export async function adminUsers(q = '', offset = 0) { return (await request(`/admin/users?q=${encodeURIComponent(q)}&offset=${offset}`)).json(); }
export async function adminWrite(path, body, method = 'POST') {
  const response = await request(`/admin/${path}`, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  return response.status === 204 ? null : response.json();
}
