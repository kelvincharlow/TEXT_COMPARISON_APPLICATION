const API_BASE = "/api/v1";

async function parseError(response) {
  try {
    const body = await response.json();
    return body.detail || "The request could not be completed.";
  } catch {
    return "The service returned an unexpected response.";
  }
}

export async function compareDocuments(original, revised) {
  const formData = new FormData();
  formData.append("original", original);
  formData.append("revised", revised);

  const response = await fetch(`${API_BASE}/compare`, {
    method: "POST",
    body: formData,
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function downloadRedline(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.blob();
}

export async function releaseComparison(comparisonId) {
  if (!comparisonId) return;
  await fetch(`${API_BASE}/comparisons/${comparisonId}`, { method: "DELETE" });
}

