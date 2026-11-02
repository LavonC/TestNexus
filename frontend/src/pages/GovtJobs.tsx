import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Landmark,
  Calendar,
  AlertTriangle,
  FileText,
  ExternalLink,
  RefreshCw,
  Building2,
  Clock,
  ShieldAlert,
} from "lucide-react";
import { api } from "../api/client";
import { JobOpening } from "../types";

export const GovtJobs: React.FC = () => {
  const [jobs, setJobs] = useState<JobOpening[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadGovtJobs();
  }, []);

  const loadGovtJobs = async () => {
    try {
      setLoading(true);
      const data = await api.getGovtJobs(true);
      setJobs(data);
    } catch {
      setJobs([]);
    } finally {
      setLoading(false);
    }
  };

  const getUrgencyBadge = (deadlineStr?: string) => {
    if (!deadlineStr) {
      return (
        <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-slate-800 text-slate-400 border border-slate-700">
          No deadline stated
        </span>
      );
    }

    const deadline = new Date(deadlineStr).getTime();
    const now = new Date().getTime();
    const diffDays = Math.ceil((deadline - now) / (1000 * 60 * 60 * 24));

    if (diffDays <= 0) {
      return (
        <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-slate-800 text-slate-400 border border-slate-700">
          Expired
        </span>
      );
    }

    if (diffDays <= 3) {
      return (
        <span className="px-2.5 py-1 rounded-full text-xs font-bold bg-rose-500/10 text-rose-400 border border-rose-500/30 flex items-center space-x-1 animate-pulse">
          <ShieldAlert className="h-3.5 w-3.5 text-rose-400" />
          <span>{diffDays} day{diffDays === 1 ? "" : "s"} left — Closing Soon!</span>
        </span>
      );
    }

    if (diffDays <= 7) {
      return (
        <span className="px-2.5 py-1 rounded-full text-xs font-bold bg-amber-500/10 text-amber-400 border border-amber-500/30 flex items-center space-x-1">
          <Clock className="h-3.5 w-3.5 text-amber-400" />
          <span>{diffDays} days remaining</span>
        </span>
      );
    }

    return (
      <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 flex items-center space-x-1">
        <Calendar className="h-3.5 w-3.5" />
        <span>Closes {deadlineStr} ({diffDays} days)</span>
      </span>
    );
  };

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      {/* Header */}
      <div className="bg-gradient-to-r from-amber-950/30 via-slate-900 to-slate-900 border border-amber-900/30 rounded-3xl p-6 sm:p-8 shadow-xl">
        <div className="flex items-center space-x-3 mb-2">
          <div className="p-3 rounded-2xl bg-amber-500/10 text-amber-400 border border-amber-500/20">
            <Landmark className="h-6 w-6" />
          </div>
          <div>
            <h1 className="text-2xl sm:text-3xl font-extrabold text-white">
              Goa Public Sector & IT Circulars
            </h1>
            <p className="text-xs text-slate-400">
              Automated tracking of GPSC, CBES, GEL, and Goa Department of Information Technology notifications.
            </p>
          </div>
        </div>
      </div>

      {/* Content */}
      {loading ? (
        <div className="py-20 flex justify-center">
          <RefreshCw className="h-8 w-8 text-amber-400 animate-spin" />
        </div>
      ) : jobs.length === 0 ? (
        <div className="py-16 text-center bg-slate-900/40 rounded-3xl border border-slate-800">
          <Landmark className="h-12 w-12 text-slate-600 mx-auto mb-3" />
          <h3 className="text-base font-semibold text-white">No active government IT notifications</h3>
          <p className="text-xs text-slate-400 mt-1">
            New public circulars will be displayed here as soon as published by Goa commissions.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {jobs.map((job, idx) => (
            <div
              key={idx}
              className="bg-slate-900/60 border border-slate-800 rounded-3xl p-6 shadow-xl flex flex-col md:flex-row md:items-center justify-between gap-6 transition-all hover:border-slate-700"
            >
              <div className="space-y-2 max-w-2xl">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs font-bold text-amber-400 flex items-center space-x-1">
                    <Building2 className="h-3.5 w-3.5" />
                    <span>{job.company_name}</span>
                  </span>
                  {job.department && (
                    <span className="text-xs text-slate-400">
                      • {job.department}
                    </span>
                  )}
                </div>

                <h2 className="text-lg font-bold text-white leading-snug">
                  {job.title}
                </h2>

                <div className="flex flex-wrap items-center gap-3 text-xs text-slate-400">
                  {job.experience_level && (
                    <span>Eligibility: {job.experience_level}</span>
                  )}
                  {job.tech_stack && job.tech_stack.length > 0 && (
                    <div className="flex flex-wrap gap-1">
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

                {job.notes && (
                  <p className="text-xs text-slate-400 italic pt-1">{job.notes}</p>
                )}
              </div>

              {/* Deadline & Actions */}
              <div className="flex flex-col sm:flex-row md:flex-col items-start md:items-end justify-between gap-3 shrink-0">
                {getUrgencyBadge(job.application_deadline)}

                <div className="flex items-center space-x-2 pt-1">
                  {job.source_url && (
                    <a
                      href={job.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold transition-colors flex items-center space-x-1.5 border border-slate-700"
                    >
                      <FileText className="h-4 w-4 text-amber-400" />
                      <span>View Circular PDF</span>
                    </a>
                  )}

                  {job.apply_url && (
                    <a
                      href={job.apply_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="px-4 py-2 rounded-xl bg-amber-500 hover:bg-amber-600 text-slate-950 text-xs font-bold transition-colors flex items-center space-x-1.5 shadow-md"
                    >
                      <span>Apply Online</span>
                      <ExternalLink className="h-3.5 w-3.5" />
                    </a>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
