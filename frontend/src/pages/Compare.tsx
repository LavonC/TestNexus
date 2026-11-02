import React, { useEffect, useState } from "react";
import { useSearchParams, Link } from "react-router-dom";
import {
  Scale,
  Building2,
  MapPin,
  Code2,
  Briefcase,
  ExternalLink,
  Plus,
  X,
  RefreshCw,
} from "lucide-react";
import { api } from "../api/client";
import { Company } from "../types";

export const Compare: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [companies, setCompanies] = useState<Company[]>([]);
  const [allCompanies, setAllCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedToAdd, setSelectedToAdd] = useState("");

  const namesParam = searchParams.get("names") || "";

  useEffect(() => {
    loadAllList();
  }, []);

  useEffect(() => {
    if (namesParam) {
      const names = namesParam.split(",").map((s) => s.trim()).filter(Boolean);
      if (names.length > 0) {
        loadComparison(names);
      } else {
        setCompanies([]);
        setLoading(false);
      }
    } else {
      setCompanies([]);
      setLoading(false);
    }
  }, [namesParam]);

  const loadAllList = async () => {
    try {
      const list = await api.getCompanies({ limit: 100 });
      setAllCompanies(list);
    } catch {
      // ignore
    }
  };

  const loadComparison = async (names: string[]) => {
    try {
      setLoading(true);
      const data = await api.compareCompanies(names);
      setCompanies(data);
    } catch {
      setCompanies([]);
    } finally {
      setLoading(false);
    }
  };

  const handleAddCompany = () => {
    if (!selectedToAdd) return;
    const current = namesParam.split(",").map((s) => s.trim()).filter(Boolean);
    if (!current.includes(selectedToAdd)) {
      if (current.length >= 3) {
        alert("Maximum 3 companies can be compared simultaneously.");
        return;
      }
      const updated = [...current, selectedToAdd];
      setSearchParams({ names: updated.join(",") });
    }
    setSelectedToAdd("");
  };

  const handleRemoveCompany = (name: string) => {
    const current = namesParam.split(",").map((s) => s.trim()).filter(Boolean);
    const updated = current.filter((c) => c !== name);
    setSearchParams(updated.length > 0 ? { names: updated.join(",") } : {});
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-white flex items-center space-x-2">
            <Scale className="h-7 w-7 text-emerald-400" />
            <span>Side-by-Side Company Comparison</span>
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Compare up to 3 Goa tech employers across locations, tech stacks, and current hiring activity.
          </p>
        </div>

        {/* Add Company Selector */}
        <div className="flex items-center space-x-2">
          <select
            value={selectedToAdd}
            onChange={(e) => setSelectedToAdd(e.target.value)}
            className="bg-slate-900 border border-slate-700 rounded-xl px-3 py-2 text-xs text-white focus:outline-none focus:border-emerald-500"
          >
            <option value="">Select company to add...</option>
            {allCompanies.map((c) => (
              <option key={c.company_name} value={c.company_name}>
                {c.company_name}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={handleAddCompany}
            disabled={!selectedToAdd}
            className="px-3 py-2 bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-bold rounded-xl text-xs transition-colors disabled:opacity-40 flex items-center space-x-1"
          >
            <Plus className="h-3.5 w-3.5" />
            <span>Add</span>
          </button>
        </div>
      </div>

      {loading ? (
        <div className="py-20 flex justify-center">
          <RefreshCw className="h-8 w-8 text-emerald-400 animate-spin" />
        </div>
      ) : companies.length === 0 ? (
        <div className="py-20 text-center bg-slate-900/40 rounded-3xl border border-slate-800">
          <Scale className="h-12 w-12 text-slate-600 mx-auto mb-3" />
          <h3 className="text-base font-semibold text-white">No companies selected</h3>
          <p className="text-xs text-slate-400 mt-1 max-w-sm mx-auto">
            Choose companies from the dropdown above or check "Compare" on cards in the Companies directory.
          </p>
          <Link
            to="/companies"
            className="mt-4 inline-block px-4 py-2 bg-slate-800 hover:bg-slate-700 text-emerald-400 text-xs font-semibold rounded-lg transition-colors"
          >
            Browse Companies
          </Link>
        </div>
      ) : (
        <div className="overflow-x-auto pb-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 min-w-[700px]">
            {companies.map((comp) => (
              <div
                key={comp.company_name}
                className="bg-slate-900/70 border border-slate-800 rounded-3xl p-6 shadow-xl flex flex-col justify-between space-y-6 relative"
              >
                {/* Remove button */}
                <button
                  type="button"
                  onClick={() => handleRemoveCompany(comp.company_name)}
                  className="absolute top-4 right-4 p-1.5 rounded-lg text-slate-400 hover:text-rose-400 hover:bg-slate-800 transition-colors"
                  title="Remove from comparison"
                >
                  <X className="h-4 w-4" />
                </button>

                {/* Company Name & Domain */}
                <div className="space-y-3">
                  <div>
                    <h2 className="text-xl font-black text-white pr-6">
                      {comp.company_name}
                    </h2>
                    <span className="text-xs text-emerald-400 font-medium">
                      {comp.core_domain || "Tech / Software"}
                    </span>
                  </div>

                  <span
                    className={`inline-block text-xs font-semibold px-2.5 py-0.5 rounded-full border ${
                      comp.hiring_status === "Actively Hiring"
                        ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
                        : "bg-slate-800 text-slate-400 border-slate-700"
                    }`}
                  >
                    {comp.hiring_status || "Unknown"}
                  </span>

                  {comp.summary && (
                    <p className="text-xs text-slate-300 line-clamp-3">
                      {comp.summary}
                    </p>
                  )}
                </div>

                {/* Locations */}
                <div className="space-y-1.5 border-t border-slate-800 pt-4">
                  <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider flex items-center space-x-1">
                    <MapPin className="h-3.5 w-3.5 text-rose-400" />
                    <span>Goa Office Locations</span>
                  </div>
                  <div className="text-xs text-slate-200">
                    {comp.goa_locations && comp.goa_locations.length > 0
                      ? comp.goa_locations.join(", ")
                      : "Location not confirmed"}
                  </div>
                </div>

                {/* Tech Stack */}
                <div className="space-y-1.5 border-t border-slate-800 pt-4">
                  <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider flex items-center space-x-1">
                    <Code2 className="h-3.5 w-3.5 text-teal-400" />
                    <span>Tech Stack</span>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {comp.tech_stack && comp.tech_stack.length > 0 ? (
                      comp.tech_stack.map((t, idx) => (
                        <span
                          key={idx}
                          className="px-2 py-0.5 rounded bg-slate-800 text-[10px] font-mono text-slate-300"
                        >
                          {t}
                        </span>
                      ))
                    ) : (
                      <span className="text-xs text-slate-500">Not specified</span>
                    )}
                  </div>
                </div>

                {/* Openings count & sample */}
                <div className="space-y-2 border-t border-slate-800 pt-4">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-semibold text-slate-400 flex items-center space-x-1">
                      <Briefcase className="h-3.5 w-3.5 text-emerald-400" />
                      <span>Active Openings</span>
                    </span>
                    <span className="font-bold text-white text-sm">
                      {comp.opening_count || 0}
                    </span>
                  </div>

                  {comp.active_openings && comp.active_openings.length > 0 && (
                    <ul className="space-y-1 text-xs text-slate-300">
                      {comp.active_openings.slice(0, 3).map((op, idx) => (
                        <li key={idx} className="truncate text-slate-300">
                          • {op.title}
                        </li>
                      ))}
                      {comp.active_openings.length > 3 && (
                        <li className="text-[11px] text-slate-500">
                          +{comp.active_openings.length - 3} more openings
                        </li>
                      )}
                    </ul>
                  )}
                </div>

                {/* View profile button */}
                <div className="pt-2">
                  <Link
                    to={`/company/${encodeURIComponent(comp.company_name)}`}
                    className="w-full py-2 bg-slate-800 hover:bg-slate-700 text-white rounded-xl text-xs font-semibold transition-colors flex items-center justify-center space-x-1 border border-slate-700"
                  >
                    <span>Full Profile</span>
                    <ExternalLink className="h-3.5 w-3.5" />
                  </Link>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
