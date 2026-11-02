import React, { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  Building2,
  MapPin,
  Briefcase,
  Search,
  Filter,
  ExternalLink,
  Scale,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import { api } from "../api/client";
import { Company } from "../types";

export const Companies: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const [companies, setCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState(searchParams.get("q") || "");
  const [location, setLocation] = useState(searchParams.get("location") || "");
  const [hiringStatus, setHiringStatus] = useState(
    searchParams.get("hiring_status") || ""
  );
  const [selectedForCompare, setSelectedForCompare] = useState<string[]>([]);

  useEffect(() => {
    loadCompanies();
  }, [searchParams]);

  const loadCompanies = async () => {
    try {
      setLoading(true);
      const data = await api.getCompanies({
        q: searchParams.get("q") || undefined,
        location: searchParams.get("location") || undefined,
        hiring_status: searchParams.get("hiring_status") || undefined,
        limit: 100,
      });
      setCompanies(data);
    } catch {
      setCompanies([]);
    } finally {
      setLoading(false);
    }
  };

  const handleFilterSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const params = new URLSearchParams();
    if (search.trim()) params.set("q", search.trim());
    if (location.trim()) params.set("location", location.trim());
    if (hiringStatus.trim()) params.set("hiring_status", hiringStatus.trim());
    setSearchParams(params);
  };

  const handleClearFilters = () => {
    setSearch("");
    setLocation("");
    setHiringStatus("");
    setSearchParams(new URLSearchParams());
  };

  const toggleCompare = (companyName: string) => {
    if (selectedForCompare.includes(companyName)) {
      setSelectedForCompare(selectedForCompare.filter((c) => c !== companyName));
    } else {
      if (selectedForCompare.length >= 3) {
        alert("You can compare up to 3 companies simultaneously.");
        return;
      }
      setSelectedForCompare([...selectedForCompare, companyName]);
    }
  };

  const handleCompareClick = () => {
    if (selectedForCompare.length < 2) {
      alert("Please select at least 2 companies to compare.");
      return;
    }
    navigate(`/compare?names=${encodeURIComponent(selectedForCompare.join(","))}`);
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-white flex items-center space-x-2">
            <Building2 className="h-7 w-7 text-emerald-400" />
            <span>Goa Tech Company Directory</span>
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Browse and filter IT companies operating in Panaji, Verna, Margao, and across Goa.
          </p>
        </div>

        {/* Floating compare button if items selected */}
        {selectedForCompare.length > 0 && (
          <div className="flex items-center space-x-3 bg-slate-900 border border-slate-700 rounded-xl px-4 py-2 shadow-lg">
            <span className="text-xs text-slate-300 font-medium">
              Selected ({selectedForCompare.length}/3)
            </span>
            <button
              onClick={handleCompareClick}
              disabled={selectedForCompare.length < 2}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-emerald-500 hover:bg-emerald-600 text-slate-950 transition-colors flex items-center space-x-1.5 disabled:opacity-40"
            >
              <Scale className="h-3.5 w-3.5" />
              <span>Compare Now</span>
            </button>
            <button
              onClick={() => setSelectedForCompare([])}
              className="text-xs text-slate-400 hover:text-white"
            >
              Clear
            </button>
          </div>
        )}
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
            placeholder="Search company name, domain, tech..."
            className="w-full bg-slate-950 border border-slate-700 rounded-lg pl-9 pr-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-emerald-500"
          />
        </div>

        <div className="w-full sm:w-auto min-w-[150px]">
          <select
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-emerald-500"
          >
            <option value="">All Locations</option>
            <option value="Panaji">Panaji</option>
            <option value="Verna">Verna Industrial Estate</option>
            <option value="Margao">Margao</option>
            <option value="Porvorim">Porvorim</option>
            <option value="Mapusa">Mapusa</option>
            <option value="Kundaim">Kundaim</option>
          </select>
        </div>

        <div className="w-full sm:w-auto min-w-[160px]">
          <select
            value={hiringStatus}
            onChange={(e) => setHiringStatus(e.target.value)}
            className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-emerald-500"
          >
            <option value="">All Hiring Statuses</option>
            <option value="Actively Hiring">Actively Hiring</option>
            <option value="Talent Pool / General">Talent Pool / General</option>
            <option value="No Immediate Openings">No Immediate Openings</option>
          </select>
        </div>

        <button
          type="submit"
          className="px-4 py-2 bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-semibold text-sm rounded-lg transition-colors flex items-center space-x-1.5"
        >
          <Filter className="h-4 w-4" />
          <span>Filter</span>
        </button>

        {(search || location || hiringStatus) && (
          <button
            type="button"
            onClick={handleClearFilters}
            className="px-3 py-2 text-sm text-slate-400 hover:text-white transition-colors"
          >
            Reset
          </button>
        )}
      </form>

      {/* Grid of Company Cards */}
      {loading ? (
        <div className="py-20 flex justify-center">
          <RefreshCw className="h-8 w-8 text-emerald-400 animate-spin" />
        </div>
      ) : companies.length === 0 ? (
        <div className="py-16 text-center bg-slate-900/40 rounded-3xl border border-slate-800">
          <Building2 className="h-12 w-12 text-slate-600 mx-auto mb-3" />
          <h3 className="text-base font-semibold text-white">No companies found</h3>
          <p className="text-xs text-slate-400 mt-1">
            Try adjusting your search query or location filter.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {companies.map((comp) => {
            const isComparing = selectedForCompare.includes(comp.company_name);
            const isActivelyHiring = comp.hiring_status === "Actively Hiring";
            const openingsCount = comp.opening_count || 0;

            return (
              <div
                key={comp.company_name}
                className="bg-slate-900/60 border border-slate-800 hover:border-slate-700 rounded-3xl p-6 shadow-xl flex flex-col justify-between transition-all hover:-translate-y-1 group"
              >
                <div>
                  <div className="flex items-start justify-between gap-3 mb-2">
                    <Link
                      to={`/company/${encodeURIComponent(comp.company_name)}`}
                      className="text-lg font-bold text-white group-hover:text-emerald-400 transition-colors line-clamp-1"
                    >
                      {comp.company_name}
                    </Link>
                    <span
                      className={`text-[11px] font-semibold px-2.5 py-0.5 rounded-full shrink-0 border ${
                        isActivelyHiring
                          ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
                          : "bg-slate-800 text-slate-400 border-slate-700"
                      }`}
                    >
                      {comp.hiring_status || "Unknown"}
                    </span>
                  </div>

                  {comp.core_domain && (
                    <div className="text-xs text-slate-400 font-medium mb-3">
                      {comp.core_domain}
                    </div>
                  )}

                  {comp.summary && (
                    <p className="text-xs text-slate-300 line-clamp-2 mb-4 leading-relaxed">
                      {comp.summary}
                    </p>
                  )}

                  {/* Locations */}
                  {comp.goa_locations && comp.goa_locations.length > 0 && (
                    <div className="flex items-center space-x-1.5 text-xs text-slate-400 mb-3">
                      <MapPin className="h-3.5 w-3.5 text-rose-400 shrink-0" />
                      <span className="line-clamp-1">
                        {Array.isArray(comp.goa_locations)
                          ? comp.goa_locations.join(", ")
                          : String(comp.goa_locations)}
                      </span>
                    </div>
                  )}

                  {/* Tech stack pills */}
                  {comp.tech_stack && comp.tech_stack.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mb-4">
                      {comp.tech_stack.slice(0, 4).map((tech, idx) => (
                        <span
                          key={idx}
                          className="px-2 py-0.5 rounded-md bg-slate-800/80 text-[11px] font-mono text-slate-300 border border-slate-700/60"
                        >
                          {tech}
                        </span>
                      ))}
                      {comp.tech_stack.length > 4 && (
                        <span className="px-2 py-0.5 rounded-md bg-slate-800/40 text-[10px] text-slate-500">
                          +{comp.tech_stack.length - 4}
                        </span>
                      )}
                    </div>
                  )}
                </div>

                <div className="pt-4 border-t border-slate-800 flex items-center justify-between text-xs">
                  <div className="flex items-center space-x-1 text-slate-400">
                    <Briefcase className="h-3.5 w-3.5 text-emerald-400" />
                    <span className="font-semibold text-white">{openingsCount}</span>
                    <span>openings</span>
                  </div>

                  <div className="flex items-center space-x-2">
                    <button
                      type="button"
                      onClick={() => toggleCompare(comp.company_name)}
                      className={`p-1.5 rounded-lg border text-xs transition-colors flex items-center space-x-1 ${
                        isComparing
                          ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
                          : "border-slate-800 text-slate-400 hover:text-white hover:bg-slate-800"
                      }`}
                      title={isComparing ? "Remove from comparison" : "Add to comparison"}
                    >
                      <Scale className="h-3.5 w-3.5" />
                      <span>{isComparing ? "Selected" : "Compare"}</span>
                    </button>

                    <Link
                      to={`/company/${encodeURIComponent(comp.company_name)}`}
                      className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-white font-medium transition-colors"
                    >
                      Details
                    </Link>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
