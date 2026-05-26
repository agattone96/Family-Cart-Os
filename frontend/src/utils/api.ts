const rawBackendUrl = process.env.EXPO_PUBLIC_BACKEND_URL?.trim();

function getApiBaseUrl() {
  if (!rawBackendUrl) {
    throw new Error('EXPO_PUBLIC_BACKEND_URL is not configured for this build.');
  }

  if (rawBackendUrl.startsWith('postgresql://') || rawBackendUrl.startsWith('postgres://')) {
    throw new Error(
      'EXPO_PUBLIC_BACKEND_URL must be an https:// backend URL (for example https://<render-service>.onrender.com), not a database URL.',
    );
  }

  let parsedUrl: URL;
  try {
    parsedUrl = new URL(rawBackendUrl);
  } catch {
    throw new Error('EXPO_PUBLIC_BACKEND_URL must be a valid absolute https:// URL.');
  }

  if (parsedUrl.protocol !== 'https:') {
    throw new Error('EXPO_PUBLIC_BACKEND_URL must use https://.');
  }

  const baseUrl = rawBackendUrl.replace(/\/+$/, '');
  return `${baseUrl}/api`;
}

let cachedApiBaseUrl: string | null = null;

function resolveApiBaseUrl() {
  if (!cachedApiBaseUrl) {
    cachedApiBaseUrl = getApiBaseUrl();
  }
  return cachedApiBaseUrl;
}

let authToken: string | null = null;

export function setApiToken(token: string | null) {
  authToken = token;
}

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request(path: string, options?: RequestInit) {
  const apiBaseUrl = resolveApiBaseUrl();
  const headers = new Headers(options?.headers || {});
  if (!headers.has('Content-Type') && options?.body) headers.set('Content-Type', 'application/json');
  if (authToken) headers.set('Authorization', `Bearer ${authToken}`);

  const res = await fetch(`${apiBaseUrl}${path}`, {
    ...options,
    headers,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(err.detail || 'Request failed', res.status);
  }

  if (res.status === 204) return null;
  return res.json();
}

export interface InventoryQuery {
  location?: string;
  search?: string;
  lowStock?: boolean;
  expiringSoon?: boolean;
  includeArchived?: boolean;
}

function buildInventoryQuery(opts?: InventoryQuery): string {
  if (!opts) return '';
  const params = new URLSearchParams();
  if (opts.location) params.set('location', opts.location);
  if (opts.search) params.set('search', opts.search);
  if (opts.lowStock) params.set('low_stock', 'true');
  if (opts.expiringSoon) params.set('expiring_soon', 'true');
  if (opts.includeArchived) params.set('include_archived', 'true');
  const qs = params.toString();
  return qs ? `?${qs}` : '';
}

export const api = {
  signup: (data: { name: string; email: string; password: string }) =>
    request('/auth/signup', { method: 'POST', body: JSON.stringify(data) }),
  login: (data: { email: string; password: string }) =>
    request('/auth/login', { method: 'POST', body: JSON.stringify(data) }),
  me: () => request('/auth/me'),
  logout: () => request('/auth/logout', { method: 'POST' }),

  getProfile: () => request('/profile'),
  updateProfile: (data: any) => request('/profile', { method: 'PUT', body: JSON.stringify(data) }),
  resetProfile: () => request('/profile/reset', { method: 'POST' }),

  getInventory: (locationOrQuery?: string | InventoryQuery) => {
    if (typeof locationOrQuery === 'string') {
      return request(`/inventory${locationOrQuery ? `?location=${locationOrQuery}` : ''}`);
    }
    return request(`/inventory${buildInventoryQuery(locationOrQuery)}`);
  },
  getInventoryDashboard: () => request('/inventory/dashboard'),
  addInventoryItem: (item: any) => request('/inventory', { method: 'POST', body: JSON.stringify(item) }),
  addInventoryBatch: (items: any[]) => request('/inventory/batch', { method: 'POST', body: JSON.stringify(items) }),
  updateInventoryItem: (id: string, data: any) => request(`/inventory/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  archiveInventoryItem: (id: string) => request(`/inventory/${id}/archive`, { method: 'POST' }),
  deleteInventoryItem: (id: string) => request(`/inventory/${id}`, { method: 'DELETE' }),
  extractPhoto: (image_base64: string, location: string) =>
    request('/inventory/extract-photo', { method: 'POST', body: JSON.stringify({ image_base64, location }) }),

  getRequiredItems: () => request('/required-items'),
  addRequiredItem: (item: any) => request('/required-items', { method: 'POST', body: JSON.stringify(item) }),
  updateRequiredItem: (id: string, data: any) => request(`/required-items/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteRequiredItem: (id: string) => request(`/required-items/${id}`, { method: 'DELETE' }),

  generatePlan: (data: any) => request('/generate-plan', { method: 'POST', body: JSON.stringify(data) }),
  getCurrentPlan: () => request('/current-plan'),
  updateCurrentPlan: (plan: any) => request('/current-plan', { method: 'PUT', body: JSON.stringify({ plan }) }),
  removeRecipe: (recipeId: string) => request(`/current-plan/recipe/${recipeId}`, { method: 'DELETE' }),
  regenerateRecipe: (recipeId: string, preference: string) =>
    request('/regenerate-recipe', { method: 'POST', body: JSON.stringify({ recipe_id: recipeId, preference }) }),

  getHistory: () => request('/history'),
  saveToHistory: () => request('/history/save', { method: 'POST' }),
  duplicateFromHistory: (id: string) => request(`/history/${id}/duplicate`, { method: 'POST' }),
};
