import React, { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import {
  Building2,
  MapPin,
  Globe,
  Mail,
  Briefcase,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  History,
  ArrowLeft,
  RefreshCw,
  Bookmark,
  Calendar,
} from "lucide-react";
import { api } from "../api/client";
import { Company, JobOpening } from "../types";

export const CompanyProfile: React.FC = () => {
  const { name } = useParams<{ name: string }>();
  const [company, setCompany] = useState<Company | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [savedJobKeys, setSavedJobKeys] = useState<string[]>([]);

  useEffect(() => {
    // Load bookmarks
    try {
      const saved = JSON.parse(localStorage.getItem("goait_saved_jobs") || "[]");
      setSavedJobKeys(saved.map((j: JobOpening) => `${j.company_name}:::${j.title}`));
    } catch {
      // ignore
    }

    if (name) {
      loadProfile(name);
    }
  }, [name]);

  const loadProfile = async (companyName: string) => {
    try {
      setLoading(true);
      const data = await api.getCompany(companyName);
      setCompany(data);
      setError(null);
    } catch (err: any) {
      setError(err.message || "Failed to load company profile");
    } finally {
      setLoading(false);
    }
  };

  const toggleBookmark = (job: JobOpening) => {
    try {
      const key = `${job.company_name}:::${job.title}`;
      const saved: JobOpening[] = JSON.parse(
        localStorage.getItem("goait_saved_jobs") || "[]"
      );
      if (savedJobKeys.includes(key)) {
        const next = saved.filter(
          (j) => `${j.company_name}:::${j.title}` !== key
        );
        localStorage.setItem("goait_saved_jobs", JSON.stringify(next));
        setSavedJobKeys(savedJobKeys.filter((k) => k !== key));
      } else {
        const next = [...saved, job];
        localStorage.setItem("goait_saved_jobs", JSON.stringify(next));
        setSavedJobKeys([...savedJobKeys, key]);
      }
    } catch {
      // ignore
    }
  };

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center min-h-[60vh]">
        <RefreshCw className="h-8 w-8 text-emerald-400 animate-spin" />
      </div>
    );
  }

  if (error || !company) {
    return (
      <div className="max-w-4xl mx-auto px-4 py-16 text-center">
        <div className="p-6 bg-slate-900 border border-slate-800 rounded-3xl">
          <p className="text-white font-semibold mb-2">Company Not Found</p>
          <p className="text-xs text-slate-400 mb-6">{error || "The requested company does not exist in the database."}</p>
          <Link
            to="/companies"
            className="px-4 py-2 bg-emerald-500 hover:bg-emerald-600 text-slate-950 text-sm font-semibold rounded-lg transition-colors inline-flex items-center space-x-2"
          >
            <ArrowLeft className="h-4 w-4" />
            <span>Back to Directory</span>
          </Link>
        </div>
      </div>
    );
  }

  const activeOpenings = company.active_openings || [];
  const historicalOpenings = company.historical_openings || [];

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
      {/* Back button */}
      <Link
        to="/companies"
        className="inline-flex items-center space-x-2 text-xs font-medium text-slate-400 hover:text-white transition-colors"
      >
        <ArrowLeft className="h-4 w-4" />
        <span>Back to Companies</span>
      </Link>

      {/* Profile Header */}
      <div className="bg-slate-900/70 border border-slate-800 rounded-3xl p-6 sm:p-8 shadow-xl">
        <div className="flex flex-col md:flex-row md:items-start justify-between gap-6">
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-2xl sm:text-3xl font-extrabold text-white">
                {company.company_name}
              </h1>
              <span
                className={`text-xs font-semibold px-3 py-1 rounded-full border ${
                  company.hiring_status === "Actively Hiring"
                    ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
                    : "bg-slate-800 text-slate-400 border-slate-700"
                }`}
              >
                {company.hiring_status || "Unknown"}
              </span>
            </div>

            {company.core_domain && (
              <div className="text-sm font-medium text-emerald-400">
                {company.core_domain}
              </div>
            )}

            {company.summary && (
              <p className="text-sm text-slate-300 max-w-2xl leading-relaxed">
                {company.summary}
              </p>
            )}

            {/* Meta tags */}
            <div className="flex flex-wrap gap-4 pt-2 text-xs text-slate-400">
              {company.goa_locations && company.goa_locations.length > 0 && (
                <div className="flex items-center space-x-1.5">
                  <MapPin className="h-4 w-4 text-rose-400" />
                  <span>
                    {Array.isArray(company.goa_locations)
                      ? company.goa_locations.join(", ")
                      : String(company.goa_locations)}
                  </span>
                </div>
              )}

              {company.contact_email && (
                <div className="flex items-center space-x-1.5">
                  <Mail className="h-4 w-4 text-teal-400" />
                  <a
                    href={`mailto:${company.contact_email}`}
                    className="hover:underline text-teal-300"
                  >
                    {company.contact_email}
                  </a>
                </div>
              )}
            </div>
          </div>

          {/* Action Links */}
          <div className="flex flex-wrap md:flex-col gap-2 shrink-0">
            {company.careers_url && (
              <a
                href={company.careers_url}
                target="_blank"
                rel="noopener noreferrer"
                className="px-4 py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-600 text-slate-950 text-xs font-bold transition-colors flex items-center justify-center space-x-2 shadow-lg"
              >
                <ExternalLink className="h-4 w-4" />
                <span>Careers Portal</span>
              </a>
            )}
            {company.website_url && (
              <a
                href={company.website_url}
                target="_blank"
                rel="noopener noreferrer"
                className="px-4 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold transition-colors flex items-center justify-center space-x-2 border border-slate-700"
              >
                <Globe className="h-4 w-4" />
                <span>Website</span>
              </a>
            )}
          </div>
        </div>

        {/* Primary Tech Stack */}
        {company.tech_stack && company.tech_stack.length > 0 && (
          <div className="mt-6 pt-6 border-t border-slate-800">
            <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
              Primary Tech Stack
            </div>
            <div className="flex flex-wrap gap-2">
              {company.tech_stack.map((t, idx) => (
                <span
                  key={idx}
                  className="px-2.5 py-1 rounded-lg bg-slate-800 text-xs font-mono text-emerald-300 border border-slate-700"
                >
                  {t}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Active Openings */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <Briefcase className="h-5 w-5 text-emerald-400" />
            <h2 className="text-lg font-bold text-white">
              Active Openings ({activeOpenings.length})
            </h2>
          </div>
        </div>

        {activeOpenings.length === 0 ? (
          <div className="p-8 text-center bg-slate-900/40 border border-slate-800 rounded-2xl">
            <p className="text-xs text-slate-400">
              No currently open positions detected at this time.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {activeOpenings.map((job, idx) => {
              const isSaved = savedJobKeys.includes(
                `${job.company_name}:::${job.title}`
              );
              return (
                <div
                  key={idx}
                  className="bg-slate-900/60 border border-slate-800 rounded-2xl p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4 transition-all hover:border-slate-700"
                >
                  <div className="space-y-2">
                    <div className="flex items-center space-x-2">
                      <span className="font-bold text-white text-base">
                        {job.title}
                      </span>
                      {job.is_computer_eng_relevant && (
                        <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-purple-500/10 text-purple-300 border border-purple-500/20">
                          CE Relevant
                        </span>
                      )}
                    </div>

                    <div className="flex flex-wrap items-center gap-3 text-xs text-slate-400">
                      {job.experience_level && (
                        <span>Exp: {job.experience_level}</span>
                      )}
                      {job.department && <span>Dept: {job.department}</span>}
                      {job.application_deadline && (
                        <span className="text-amber-400">
                          Deadline: {job.application_deadline}
                        </span>
                      )}
                    </div>

                    {job.tech_stack && job.tech_stack.length > 0 && (
                      <div className="flex flex-wrap gap-1.5 pt-1">
                        {job.tech_stack.map((t, tidx) => (
                          <span
                            key={tidx}
                            className="px-2 py-0.5 rounded bg-slate-800 text-[10px] font-mono text-slate-300"
                          >
                            {t}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="flex items-center space-x-2 shrink-0">
                    <button
                      type="button"
                      onClick={() => toggleBookmark(job)}
                      className={`p-2 rounded-lg border text-xs transition-colors ${
                        isSaved
                          ? "bg-amber-500/10 text-amber-400 border-amber-500/30"
                          : "border-slate-800 text-slate-400 hover:text-white"
                      }`}
                      title={isSaved ? "Remove from bookmarks" : "Save job"}
                    >
                      <Bookmark className="h-4 w-4" />
                    </button>

                    {job.apply_url && (
                      <a
                        href={job.apply_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="px-4 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-semibold text-xs transition-colors flex items-center space-x-1.5"
                      >
                        <span>Apply</span>
                        <ExternalLink className="h-3.5 w-3.5" />
                      </a>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Historical Openings Collapsible */}
      <div className="border border-slate-800 rounded-3xl overflow-hidden bg-slate-900/40">
        <button
          type="button"
          onClick={() => setShowHistory(!showHistory)}
          className="w-full px-6 py-4 flex items-center justify-between text-left hover:bg-slate-900/80 transition-colors"
        >
          <div className="flex items-center space-x-2">
            <History className="h-5 w-5 text-indigo-400" />
            <span className="font-bold text-white text-sm">
              Historical Openings Archive ({historicalOpenings.length})
            </span>
          </div>
          {showHistory ? (
            <ChevronUp className="h-5 w-5 text-slate-400" />
          ) : (
            <ChevronDown className="h-5 w-5 text-slate-400" />
          )}
        </button>

        {showHistory && (
          <div className="px-6 pb-6 pt-2 border-t border-slate-800/80 space-y-3">
            {historicalOpenings.length === 0 ? (
              <p className="text-xs text-slate-500 py-2">
                No past historical openings on record.
              </p>
            ) : (
              historicalOpenings.map((hjob, idx) => (
                <div
                  key={idx}
                  className="p-4 rounded-xl bg-slate-950/60 border border-slate-800/80 flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs"
                >
                  <div>
                    <div className="font-semibold text-slate-200">
                      {hjob.title}
                    </div>
                    <div className="text-slate-500 mt-0.5">
                      {hjob.experience_level || "Experience not specified"}
                    </div>
                  </div>

                  <div className="flex items-center space-x-4 text-slate-400 text-[11px]">
                    <div className="flex items-center space-x-1">
                      <Calendar className="h-3.5 w-3.5 text-slate-500" />
                      <span>First seen: {hjob.first_seen?.slice(0, 10) || "N/A"}</span>
                    </div>
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                        hjob.is_active
                          ? "bg-emerald-500/10 text-emerald-400"
                          : "bg-slate-800 text-slate-400"
                      }`}
                    >
                      {hjob.is_active ? "Still Open" : "Closed"}
                    </span>
                  </div>
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
};
