import {
  Company,
  HiringTrends,
  JobAlertCreate,
  JobOpening,
  PipelineStats,
  StatsResponse,
} from "../types";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

async function request<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE}${endpoint}`;
  const res = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      ...options?.headers,
    },
  });

  if (!res.ok) {
    let errorDetail = res.statusText;
    try {
      const errorJson = await res.json();
      errorDetail = errorJson.detail || errorJson.error || errorDetail;
    } catch {
      // ignore
    }
    throw new Error(errorDetail || `Request failed with status ${res.status}`);
  }

  return res.json() as Promise<T>;
}

export const api = {
  // Stats
  async getStats(): Promise<StatsResponse> {
    return request<StatsResponse>("/api/stats");
  },

  async getTrends(): Promise<{ trends: HiringTrends }> {
    return request<{ trends: HiringTrends }>("/api/stats/trends");
  },

  // Companies
  async getCompanies(params?: {
    q?: string;
    name?: string;
    location?: string;
    tech?: string;
    hiring_status?: string;
    limit?: number;
  }): Promise<Company[]> {
    const query = new URLSearchParams();
    if (params?.q) query.set("q", params.q);
    if (params?.name) query.set("name", params.name);
    if (params?.location) query.set("location", params.location);
    if (params?.tech) query.set("tech", params.tech);
    if (params?.hiring_status) query.set("hiring_status", params.hiring_status);
    if (params?.limit) query.set("limit", String(params.limit));

    const qs = query.toString();
    return request<Company[]>(`/api/companies${qs ? `?${qs}` : ""}`);
  },

  async getCompany(name: string): Promise<Company> {
    return request<Company>(`/api/companies/${encodeURIComponent(name)}`);
  },

  async compareCompanies(names: string[]): Promise<Company[]> {
    return request<Company[]>(
      `/api/companies/compare?names=${encodeURIComponent(names.join(","))}`
    );
  },

  // Jobs
  async getJobs(params?: {
    q?: string;
    company?: string;
    title?: string;
    location?: string;
    tech?: string;
    exp?: string;
    ce_only?: boolean;
    limit?: number;
  }): Promise<JobOpening[]> {
    const query = new URLSearchParams();
    if (params?.q) query.set("q", params.q);
    if (params?.company) query.set("company", params.company);
    if (params?.title) query.set("title", params.title);
    if (params?.location) query.set("location", params.location);
    if (params?.tech) query.set("tech", params.tech);
    if (params?.exp) query.set("exp", params.exp);
    if (params?.ce_only) query.set("ce_only", "true");
    if (params?.limit) query.set("limit", String(params.limit));

    const qs = query.toString();
    return request<JobOpening[]>(`/api/jobs${qs ? `?${qs}` : ""}`);
  },

  async getFresherJobs(): Promise<JobOpening[]> {
    return request<JobOpening[]>("/api/jobs/freshers");
  },

  async getGovtJobs(upcoming: boolean = true): Promise<JobOpening[]> {
    return request<JobOpening[]>(`/api/jobs/govt?upcoming=${upcoming}`);
  },

  // Alerts
  async subscribeAlert(payload: JobAlertCreate): Promise<{
    status: string;
    email: string;
    unsubscribe_token: string;
  }> {
    return request("/api/jobs/alerts", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  // Search suggest
  async getSearchSuggestions(q: string): Promise<string[]> {
    if (!q || q.length < 2) return [];
    return request<string[]>(`/api/search/suggest?q=${encodeURIComponent(q)}`);
  },

  // Chat
  async sendChat(
    question: string,
    apiKey?: string,
    model?: string
  ): Promise<{ answer: string; source: string; model_used?: string }> {
    return request("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        question,
        api_key: apiKey || null,
        model: model || null,
      }),
    });
  },
};
