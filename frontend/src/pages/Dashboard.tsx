import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Building2,
  Briefcase,
  Users,
  Code2,
  Clock,
  ArrowRight,
  TrendingUp,
  Sparkles,
  Landmark,
  GraduationCap,
  RefreshCw,
} from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { api } from "../api/client";
import { StatsResponse } from "../types";

export const Dashboard: React.FC = () => {
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [countdown, setCountdown] = useState<string>("");

  useEffect(() => {
    loadStats();
  }, []);

  const loadStats = async () => {
    try {
      setLoading(true);
      const data = await api.getStats();
      setStats(data);
      setError(null);
    } catch (err: any) {
      setError(err.message || "Failed to load dashboard data");
    } finally {
      setLoading(false);
    }
  };

  // Next run countdown calculation
  useEffect(() => {
    if (!stats?.scrape_status?.next_run_time) {
      setCountdown("Every 6 hours");
      return;
    }

    const interval = setInterval(() => {
      const nextTime = new Date(stats.scrape_status!.next_run_time!).getTime();
      const now = new Date().getTime();
      const diff = nextTime - now;

      if (diff <= 0) {
        setCountdown("Scraping now or momentarily...");
      } else {
        const hours = Math.floor(diff / (1000 * 60 * 60));
        const mins = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
        const secs = Math.floor((diff % (1000 * 60)) / 1000);
        setCountdown(`${hours}h ${mins}m ${secs}s`);
      }
    }, 1000);

    return () => clearInterval(interval);
  }, [stats]);

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center min-h-[60vh]">
        <div className="flex flex-col items-center space-y-3">
          <RefreshCw className="h-8 w-8 text-emerald-400 animate-spin" />
          <p className="text-slate-400 text-sm">Fetching Goa career intelligence...</p>
        </div>
      </div>
    );
  }

  if (error || !stats) {
    return (
      <div className="max-w-7xl mx-auto px-4 py-12 text-center">
        <div className="inline-block p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300">
          <p className="font-semibold mb-2">Error loading dashboard</p>
          <p className="text-xs text-rose-400 mb-4">{error}</p>
          <button
            onClick={loadStats}
            className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-white text-xs rounded-lg transition-colors"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  const pipeline = stats.pipeline;
  const trends = stats.trends;
  const topCompanies = trends?.top_companies || [];
  const topTech = trends?.top_tech_stack || [];

  const statCards = [
    {
      title: "Monitored Companies",
      value: pipeline.total_companies,
      subtitle: `${pipeline.completed} scanned & analyzed`,
      icon: Building2,
      color: "from-blue-500 to-indigo-500",
      link: "/companies",
    },
    {
      title: "Actively Hiring",
      value: pipeline.actively_hiring_companies,
      subtitle: "With confirmed open roles",
      icon: Users,
      color: "from-emerald-500 to-teal-500",
      link: "/companies?hiring_status=Actively Hiring",
    },
    {
      title: "Active Job Openings",
      value: pipeline.total_openings,
      subtitle: `${pipeline.total_historical_openings} historical recorded`,
      icon: Briefcase,
      color: "from-amber-500 to-orange-500",
      link: "/jobs",
    },
    {
      title: "Software & CE Roles",
      value: pipeline.ce_relevant_openings,
      subtitle: "Computer Eng. relevant",
      icon: Code2,
      color: "from-purple-500 to-pink-500",
      link: "/jobs?ce_only=true",
    },
  ];

  const colors = ["#10b981", "#3b82f6", "#8b5cf6", "#f59e0b", "#ec4899", "#06b6d4"];

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
      {/* Hero Banner */}
      <div className="relative overflow-hidden rounded-3xl bg-gradient-to-r from-slate-900 via-slate-800 to-slate-900 border border-slate-700 p-8 shadow-2xl">
        <div className="relative z-10 flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
          <div className="space-y-2 max-w-2xl">
            <div className="inline-flex items-center space-x-2 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              <Sparkles className="h-3.5 w-3.5" />
              <span>Goa Autonomous Career Intelligence Platform</span>
            </div>
            <h1 className="text-3xl sm:text-4xl font-extrabold tracking-tight text-white">
              Real-time Tech Job Market in <span className="text-emerald-400">Goa</span>
            </h1>
            <p className="text-sm text-slate-300">
              Continuous background scraping of Goan tech companies, public service portals (GPSC), and local circulars with zero AI ingestion overhead.
            </p>
          </div>

          {/* Scrape Status Card */}
          <div className="bg-slate-950/70 border border-slate-700/80 rounded-2xl p-4 flex flex-col space-y-2 min-w-[220px]">
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span className="flex items-center space-x-1.5">
                <Clock className="h-3.5 w-3.5 text-emerald-400" />
                <span>Next Background Scan</span>
              </span>
              <span className="h-2 w-2 rounded-full bg-emerald-500 animate-ping" />
            </div>
            <div className="text-lg font-bold text-white font-mono">{countdown}</div>
            <div className="text-[11px] text-slate-500">
              Interval: Every {stats.scrape_status?.interval_hours || 6} hours
            </div>
          </div>
        </div>
      </div>

      {/* Metrics Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {statCards.map((card, idx) => {
          const Icon = card.icon;
          return (
            <Link
              key={idx}
              to={card.link}
              className="group bg-slate-900/60 hover:bg-slate-800/80 border border-slate-800 hover:border-slate-700 rounded-2xl p-5 transition-all shadow-lg hover:-translate-y-0.5"
            >
              <div className="flex items-center justify-between mb-3">
                <span className="text-xs font-medium text-slate-400">{card.title}</span>
                <div
                  className={`h-9 w-9 rounded-xl bg-gradient-to-tr ${card.color} flex items-center justify-center text-white shadow`}
                >
                  <Icon className="h-4 w-4" />
                </div>
              </div>
              <div className="text-3xl font-extrabold text-white group-hover:text-emerald-400 transition-colors">
                {card.value}
              </div>
              <div className="text-xs text-slate-500 mt-1 flex items-center justify-between">
                <span>{card.subtitle}</span>
                <ArrowRight className="h-3 w-3 opacity-0 group-hover:opacity-100 transition-opacity" />
              </div>
            </Link>
          );
        })}
      </div>

      {/* Quick Action Shortcuts */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Link
          to="/jobs/freshers"
          className="flex items-center justify-between p-4 rounded-2xl bg-gradient-to-r from-blue-950/40 to-slate-900 border border-blue-900/40 hover:border-blue-700/60 transition-colors group"
        >
          <div className="flex items-center space-x-3">
            <div className="p-2.5 rounded-xl bg-blue-500/10 text-blue-400 border border-blue-500/20">
              <GraduationCap className="h-5 w-5" />
            </div>
            <div>
              <div className="text-sm font-semibold text-white group-hover:text-blue-400 transition-colors">
                Fresher & Junior Opportunities
              </div>
              <div className="text-xs text-slate-400">
                Tailored for recent college grads & entry-level engineers
              </div>
            </div>
          </div>
          <ArrowRight className="h-4 w-4 text-blue-400 group-hover:translate-x-1 transition-transform" />
        </Link>

        <Link
          to="/govt-jobs"
          className="flex items-center justify-between p-4 rounded-2xl bg-gradient-to-r from-emerald-950/40 to-slate-900 border border-emerald-900/40 hover:border-emerald-700/60 transition-colors group"
        >
          <div className="flex items-center space-x-3">
            <div className="p-2.5 rounded-xl bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              <Landmark className="h-5 w-5" />
            </div>
            <div>
              <div className="text-sm font-semibold text-white group-hover:text-emerald-400 transition-colors">
                Government IT Circulars
              </div>
              <div className="text-xs text-slate-400">
                GPSC, CBES, & NIC public sector opportunities with deadlines
              </div>
            </div>
          </div>
          <ArrowRight className="h-4 w-4 text-emerald-400 group-hover:translate-x-1 transition-transform" />
        </Link>
      </div>

      {/* Charts Section */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Top Hiring Companies */}
        <div className="bg-slate-900/60 border border-slate-800 rounded-3xl p-6 shadow-xl flex flex-col">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center space-x-2">
              <TrendingUp className="h-5 w-5 text-emerald-400" />
              <h2 className="text-base font-bold text-white">Top Hiring Companies in Goa</h2>
            </div>
            <Link to="/companies" className="text-xs text-emerald-400 hover:underline">
              View all
            </Link>
          </div>

          {topCompanies.length > 0 ? (
            <div className="h-64 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={topCompanies} layout="vertical" margin={{ left: 20, right: 20 }}>
                  <XAxis type="number" stroke="#64748b" fontSize={11} allowDecimals={false} />
                  <YAxis
                    type="category"
                    dataKey="company_name"
                    stroke="#94a3b8"
                    fontSize={12}
                    width={110}
                    tickFormatter={(val) => (val.length > 14 ? `${val.slice(0, 12)}…` : val)}
                  />
                  <Tooltip
                    contentStyle={{ backgroundColor: "#0f172a", borderColor: "#334155", borderRadius: "8px" }}
                    itemStyle={{ color: "#10b981" }}
                  />
                  <Bar dataKey="opening_count" radius={[0, 6, 6, 0]}>
                    {topCompanies.map((_, index) => (
                      <Cell key={`cell-${index}`} fill={colors[index % colors.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="h-64 flex items-center justify-center text-sm text-slate-500">
              No active company openings recorded yet.
            </div>
          )}
        </div>

        {/* Most In-Demand Tech Stack */}
        <div className="bg-slate-900/60 border border-slate-800 rounded-3xl p-6 shadow-xl flex flex-col">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center space-x-2">
              <Code2 className="h-5 w-5 text-teal-400" />
              <h2 className="text-base font-bold text-white">Most Demanded Tech Skills</h2>
            </div>
            <Link to="/jobs" className="text-xs text-teal-400 hover:underline">
              Browse jobs
            </Link>
          </div>

          {topTech.length > 0 ? (
            <div className="h-64 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={topTech} margin={{ top: 10, right: 10, bottom: 20, left: 0 }}>
                  <XAxis
                    dataKey="tech"
                    stroke="#94a3b8"
                    fontSize={11}
                    angle={-25}
                    textAnchor="end"
                    interval={0}
                  />
                  <YAxis stroke="#64748b" fontSize={11} allowDecimals={false} />
                  <Tooltip
                    contentStyle={{ backgroundColor: "#0f172a", borderColor: "#334155", borderRadius: "8px" }}
                    itemStyle={{ color: "#38bdf8" }}
                  />
                  <Bar dataKey="count" fill="#38bdf8" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="h-64 flex items-center justify-center text-sm text-slate-500">
              No tech stack skills logged yet.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
