import React, { useEffect, useState } from "react";
import { useLocation, useSearchParams, Link } from "react-router-dom";
import {
  Briefcase,
  Search,
  Filter,
  MapPin,
  ExternalLink,
  Bookmark,
  Bell,
  Code2,
  Calendar,
  RefreshCw,
  FileText,
  Building2,
  Landmark,
} from "lucide-react";
import { api } from "../api/client";
import { JobOpening } from "../types";
import { AlertModal } from "../components/AlertModal";

export const JobBoard: React.FC = () => {
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();

  const isFresherPage = location.pathname.includes("/freshers");

  const [jobs, setJobs] = useState<JobOpening[]>([]);
  const [loading, setLoading] = useState(true);
  const [savedJobKeys, setSavedJobKeys] = useState<string[]>([]);
  const [alertModalOpen, setAlertModalOpen] = useState(false);

  // Filter states
  const [search, setSearch] = useState(searchParams.get("q") || "");
  const [expLevel, setExpLevel] = useState(
    isFresherPage ? "Fresher" : searchParams.get("exp") || ""
  );
  const [tech, setTech] = useState(searchParams.get("tech") || "");
  const [loc, setLoc] = useState(searchParams.get("location") || "");
  const [ceOnly, setCeOnly] = useState(searchParams.get("ce_only") === "true");

  useEffect(() => {
    // Load bookmarks
    try {
      const saved = JSON.parse(localStorage.getItem("goait_saved_jobs") || "[]");
      setSavedJobKeys(saved.map((j: JobOpening) => `${j.company_name}:::${j.title}`));
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    loadJobs();
  }, [searchParams, isFresherPage]);

  const loadJobs = async () => {
    try {
      setLoading(true);
      let data: JobOpening[];
      if (isFresherPage) {
        data = await api.getFresherJobs();
      } else {
        data = await api.getJobs({
          q: searchParams.get("q") || undefined,
          exp: searchParams.get("exp") || undefined,
          tech: searchParams.get("tech") || undefined,
          location: searchParams.get("location") || undefined,
          ce_only: searchParams.get("ce_only") === "true" || undefined,
          limit: 150,
        });
      }
      setJobs(data);
    } catch {
      setJobs([]);
    } finally {
      setLoading(false);
    }
  };

  const handleFilterSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const params = new URLSearchParams();
    if (search.trim()) params.set("q", search.trim());
    if (expLevel.trim()) params.set("exp", expLevel.trim());
    if (tech.trim()) params.set("tech", tech.trim());
    if (loc.trim()) params.set("location", loc.trim());
    if (ceOnly) params.set("ce_only", "true");
    setSearchParams(params);
  };

  const handleClear = () => {
    setSearch("");
    setExpLevel(isFresherPage ? "Fresher" : "");
    setTech("");
    setLoc("");
    setCeOnly(false);
    setSearchParams(new URLSearchParams());
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

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-white flex items-center space-x-2">
            <Briefcase className="h-7 w-7 text-emerald-400" />
            <span>{isFresherPage ? "Fresher & Junior Tech Roles" : "Goa Tech Job Board"}</span>
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            {isFresherPage
              ? "Entry-level and 0-1 year experience opportunities across Goan IT companies."
              : "Directly scraped job openings across Goan tech companies and public departments."}
          </p>
        </div>

        {/* Job Alert Button */}
        <button
          type="button"
          onClick={() => setAlertModalOpen(true)}
          className="px-4 py-2.5 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-600 hover:to-teal-600 text-slate-950 font-bold text-xs shadow-lg transition-all flex items-center space-x-2 shrink-0 self-start md:self-auto"
        >
          <Bell className="h-4 w-4" />
          <span>Get Free Email Alerts</span>
        </button>
      </div>

      {/* Filter Bar */}
      <form
        onSubmit={handleFilterSubmit}
        className="bg-slate-900/80 border border-slate-800 rounded-2xl p-4 shadow-md flex flex-wrap gap-3 items-center"
      >
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search title, tech stack, company..."
            className="w-full bg-slate-950 border border-slate-700 rounded-lg pl-9 pr-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-emerald-500"
          />
        </div>

        {!isFresherPage && (
          <div className="w-full sm:w-auto min-w-[140px]">
            <select
              value={expLevel}
              onChange={(e) => setExpLevel(e.target.value)}
              className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-emerald-500"
            >
              <option value="">All Experience</option>
              <option value="Fresher">Fresher / 0 yrs</option>
              <option value="1-3">1-3 Years</option>
              <option value="3-5">3-5 Years</option>
              <option value="Senior">Senior / Lead</option>
            </select>
          </div>
        )}

        <div className="w-full sm:w-auto min-w-[130px]">
          <input
            type="text"
            value={tech}
            onChange={(e) => setTech(e.target.value)}
            placeholder="Tech (e.g. Python)"
            className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-emerald-500"
          />
        </div>

        <div className="flex items-center space-x-2 px-2">
          <input
            type="checkbox"
            id="ce-only"
            checked={ceOnly}
            onChange={(e) => setCeOnly(e.target.checked)}
            className="rounded bg-slate-950 border-slate-700 text-emerald-500 focus:ring-emerald-500 h-4 w-4"
          />
          <label htmlFor="ce-only" className="text-xs text-slate-300 cursor-pointer">
            CE Relevant Only
          </label>
        </div>

        <button
          type="submit"
          className="px-4 py-2 bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-semibold text-sm rounded-lg transition-colors flex items-center space-x-1.5"
        >
          <Filter className="h-4 w-4" />
          <span>Filter</span>
        </button>

        {(search || expLevel || tech || loc || ceOnly) && (
          <button
            type="button"
            onClick={handleClear}
            className="px-3 py-2 text-sm text-slate-400 hover:text-white transition-colors"
          >
            Reset
          </button>
        )}
      </form>

      {/* Results Count */}
      <div className="text-xs text-slate-400 px-1 flex items-center justify-between">
        <span>Showing {jobs.length} open position{jobs.length === 1 ? "" : "s"}</span>
      </div>

      {/* Jobs List */}
      {loading ? (
        <div className="py-20 flex justify-center">
          <RefreshCw className="h-8 w-8 text-emerald-400 animate-spin" />
        </div>
      ) : jobs.length === 0 ? (
        <div className="py-16 text-center bg-slate-900/40 rounded-3xl border border-slate-800">
          <Briefcase className="h-12 w-12 text-slate-600 mx-auto mb-3" />
          <h3 className="text-base font-semibold text-white">No job openings found</h3>
          <p className="text-xs text-slate-400 mt-1">
            Try broadening your search criteria or resetting filters.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {jobs.map((job, idx) => {
            const isSaved = savedJobKeys.includes(
              `${job.company_name}:::${job.title}`
            );
            return (
              <div
                key={idx}
                className="bg-slate-900/60 border border-slate-800 hover:border-slate-700 rounded-3xl p-5 shadow-lg flex flex-col justify-between transition-all hover:-translate-y-0.5 group"
              >
                <div className="space-y-2">
                  <div className="flex items-start justify-between gap-3">
                    <Link
                      to={`/company/${encodeURIComponent(job.company_name)}`}
                      className="text-xs font-semibold text-emerald-400 hover:underline flex items-center space-x-1"
                    >
                      <Building2 className="h-3.5 w-3.5" />
                      <span>{job.company_name}</span>
                    </Link>

                    {job.is_government && (
                      <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/10 text-amber-300 border border-amber-500/20 flex items-center space-x-1">
                        <Landmark className="h-3 w-3" />
                        <span>Govt</span>
                      </span>
                    )}
                  </div>

                  <h2 className="text-base font-bold text-white group-hover:text-emerald-300 transition-colors line-clamp-2">
                    {job.title}
                  </h2>

                  <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
                    {job.experience_level && (
                      <span className="px-2 py-0.5 rounded bg-slate-800 text-[11px] font-medium text-slate-300">
                        {job.experience_level}
                      </span>
                    )}

                    {job.department && (
                      <span className="text-[11px] text-slate-400">
                        Dept: {job.department}
                      </span>
                    )}

                    {job.application_deadline && (
                      <span className="text-[11px] text-amber-400 font-medium flex items-center space-x-1">
                        <Calendar className="h-3 w-3" />
                        <span>Deadline: {job.application_deadline}</span>
                      </span>
                    )}
                  </div>

                  {job.tech_stack && job.tech_stack.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 pt-1">
                      {job.tech_stack.map((t, tidx) => (
                        <span
                          key={tidx}
                          className="px-2 py-0.5 rounded bg-slate-800/80 text-[10px] font-mono text-slate-300 border border-slate-700/60"
                        >
                          {t}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                <div className="pt-4 mt-3 border-t border-slate-800/80 flex items-center justify-between text-xs">
                  <span className="text-[11px] text-slate-500">
                    {job.is_computer_eng_relevant ? "CE Relevant Role" : "General Role"}
                  </span>

                  <div className="flex items-center space-x-2">
                    <button
                      type="button"
                      onClick={() => toggleBookmark(job)}
                      className={`p-2 rounded-lg border text-xs transition-colors ${
                        isSaved
                          ? "bg-amber-500/10 text-amber-400 border-amber-500/30"
                          : "border-slate-800 text-slate-400 hover:text-white hover:bg-slate-800"
                      }`}
                      title={isSaved ? "Remove bookmark" : "Save job"}
                    >
                      <Bookmark className="h-4 w-4" />
                    </button>

                    {job.source_type === "PDF" && job.source_url && (
                      <a
                        href={job.source_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium transition-colors flex items-center space-x-1"
                        title="View official circular PDF"
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
                        className="px-3.5 py-1.5 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-slate-950 text-xs font-bold transition-colors flex items-center space-x-1"
                      >
                        <span>Apply</span>
                        <ExternalLink className="h-3.5 w-3.5" />
                      </a>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Job Alert Modal */}
      <AlertModal
        isOpen={alertModalOpen}
        onClose={() => setAlertModalOpen(false)}
        defaultTech={tech}
      />
    </div>
  );
};
