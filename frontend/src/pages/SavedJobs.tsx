import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Bookmark,
  Building2,
  Trash2,
  ExternalLink,
  Briefcase,
  FileText,
  Calendar,
} from "lucide-react";
import { JobOpening } from "../types";

export const SavedJobs: React.FC = () => {
  const [savedJobs, setSavedJobs] = useState<JobOpening[]>([]);

  useEffect(() => {
    loadSaved();
  }, []);

  const loadSaved = () => {
    try {
      const stored = localStorage.getItem("goait_saved_jobs");
      if (stored) {
        setSavedJobs(JSON.parse(stored));
      }
    } catch {
      setSavedJobs([]);
    }
  };

  const removeJob = (companyName: string, title: string) => {
    const updated = savedJobs.filter(
      (j) => !(j.company_name === companyName && j.title === title)
    );
    setSavedJobs(updated);
    localStorage.setItem("goait_saved_jobs", JSON.stringify(updated));
  };

  const clearAll = () => {
    if (window.confirm("Remove all saved jobs from bookmarks?")) {
      setSavedJobs([]);
      localStorage.removeItem("goait_saved_jobs");
    }
  };

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-white flex items-center space-x-2">
            <Bookmark className="h-7 w-7 text-amber-400" />
            <span>Saved Job Openings ({savedJobs.length})</span>
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Jobs bookmarked in your browser for quick application and follow-up.
          </p>
        </div>

        {savedJobs.length > 0 && (
          <button
            type="button"
            onClick={clearAll}
            className="px-3 py-1.5 rounded-lg text-xs text-rose-400 hover:text-rose-300 hover:bg-rose-500/10 border border-rose-500/20 transition-colors flex items-center space-x-1.5 self-start sm:self-auto"
          >
            <Trash2 className="h-3.5 w-3.5" />
            <span>Clear All</span>
          </button>
        )}
      </div>

      {savedJobs.length === 0 ? (
        <div className="py-20 text-center bg-slate-900/40 rounded-3xl border border-slate-800">
          <Bookmark className="h-12 w-12 text-slate-600 mx-auto mb-3" />
          <h3 className="text-base font-semibold text-white">No jobs saved yet</h3>
          <p className="text-xs text-slate-400 mt-1 max-w-sm mx-auto">
            Click the bookmark icon on any job card to save it here for later.
          </p>
          <Link
            to="/jobs"
            className="mt-4 inline-block px-4 py-2 bg-emerald-500 hover:bg-emerald-600 text-slate-950 text-xs font-bold rounded-lg transition-colors"
          >
            Explore Job Openings
          </Link>
        </div>
      ) : (
        <div className="space-y-3">
          {savedJobs.map((job, idx) => (
            <div
              key={idx}
              className="bg-slate-900/60 border border-slate-800 rounded-2xl p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4 shadow-lg transition-all hover:border-slate-700"
            >
              <div className="space-y-1.5">
                <Link
                  to={`/company/${encodeURIComponent(job.company_name)}`}
                  className="text-xs font-semibold text-emerald-400 hover:underline flex items-center space-x-1"
                >
                  <Building2 className="h-3.5 w-3.5" />
                  <span>{job.company_name}</span>
                </Link>

                <h2 className="text-base font-bold text-white leading-snug">
                  {job.title}
                </h2>

                <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
                  {job.experience_level && <span>Exp: {job.experience_level}</span>}
                  {job.department && <span>Dept: {job.department}</span>}
                  {job.application_deadline && (
                    <span className="text-amber-400 flex items-center space-x-1">
                      <Calendar className="h-3 w-3" />
                      <span>Closes: {job.application_deadline}</span>
                    </span>
                  )}
                </div>

                {job.tech_stack && job.tech_stack.length > 0 && (
                  <div className="flex flex-wrap gap-1 pt-1">
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
                  onClick={() => removeJob(job.company_name, job.title)}
                  className="p-2 rounded-lg text-slate-400 hover:text-rose-400 hover:bg-slate-800 border border-slate-800 transition-colors"
                  title="Remove from saved"
                >
                  <Trash2 className="h-4 w-4" />
                </button>

                {job.source_type === "PDF" && job.source_url && (
                  <a
                    href={job.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium transition-colors flex items-center space-x-1"
                  >
                    <FileText className="h-3.5 w-3.5" />
                    <span>PDF</span>
                  </a>
                )}

                {job.apply_url && (
                  <a
                    href={job.apply_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="px-4 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-slate-950 text-xs font-bold transition-colors flex items-center space-x-1 shadow-md"
                  >
                    <span>Apply</span>
                    <ExternalLink className="h-3.5 w-3.5" />
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
