export interface JobOpening {
  id?: number;
  company_name: string;
  title: string;
  department?: string;
  experience_level?: string;
  tech_stack: string[];
  is_computer_eng_relevant: boolean;
  source_type?: string;
  source_url?: string;
  apply_url?: string;
  notes?: string;
  application_deadline?: string;
  is_government?: boolean;
  first_seen?: string;
  last_seen?: string;
  is_active?: boolean | number;
}

export interface Company {
  company_name: string;
  website_url?: string;
  careers_url?: string;
  status?: string;
  last_scraped_at?: string;
  goa_locations: string[];
  core_domain?: string;
  tech_stack: string[];
  hiring_status: string;
  contact_email?: string;
  summary?: string;
  opening_count?: number;
  active_openings?: JobOpening[];
  historical_openings?: JobOpening[];
}

export interface PipelineStats {
  total_companies: number;
  pending: number;
  in_progress: number;
  completed: number;
  failed: number;
  total_openings: number;
  actively_hiring_companies: number;
  ce_relevant_openings: number;
  total_historical_openings: number;
}

export interface HiringTrends {
  top_companies: { company_name: string; opening_count: number }[];
  top_tech_stack: { tech: string; count: number }[];
  active_vs_closed: { status: string; count: number }[];
}

export interface StatsResponse {
  pipeline: PipelineStats;
  trends: HiringTrends;
  scrape_status?: {
    is_running: boolean;
    last_run_time?: string;
    next_run_time?: string;
    interval_hours: number;
    last_error?: string;
  };
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  source?: "gemini_user" | "gemini_server" | "offline_db" | "system";
  timestamp: string;
}

export interface JobAlertCreate {
  email: string;
  tech_filter?: string[];
  location_filter?: string[];
  ce_only?: boolean;
}

export interface SearchSuggestion {
  query: string;
  suggestions: string[];
}
