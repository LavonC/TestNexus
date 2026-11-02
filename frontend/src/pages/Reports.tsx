import React, { useEffect, useState } from "react";
import {
  FileText,
  Download,
  Rss,
  FileSpreadsheet,
  FileCode,
  Copy,
  Check,
  RefreshCw,
  Eye,
} from "lucide-react";

export const Reports: React.FC = () => {
  const [activeTab, setActiveTab] = useState<"md" | "json">("md");
  const [mdContent, setMdContent] = useState<string>("");
  const [jsonContent, setJsonContent] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    loadDigest();
  }, []);

  const loadDigest = async () => {
    try {
      setLoading(true);
      const [mdRes, jsonRes] = await Promise.all([
        fetch("/api/exports/digest.md"),
        fetch("/api/exports/digest.json"),
      ]);

      if (mdRes.ok) {
        setMdContent(await mdRes.text());
      }
      if (jsonRes.ok) {
        const jsonData = await jsonRes.json();
        setJsonContent(JSON.stringify(jsonData, null, 2));
      }
    } catch {
      setMdContent("# Unable to load digest preview\nRun a scan first or check backend connection.");
    } finally {
      setLoading(false);
    }
  };

  const handleCopy = () => {
    const text = activeTab === "md" ? mdContent : jsonContent;
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const downloadLinks = [
    {
      title: "Markdown Digest",
      desc: "Complete intelligence report formatted in Markdown.",
      url: "/api/exports/digest.md",
      filename: "goa_job_intelligence.md",
      icon: FileText,
      color: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20",
    },
    {
      title: "JSON Dataset",
      desc: "Full structured export of companies, openings, and pipeline state.",
      url: "/api/exports/digest.json",
      filename: "goa_job_intelligence.json",
      icon: FileCode,
      color: "text-blue-400 bg-blue-500/10 border-blue-500/20",
    },
    {
      title: "Jobs CSV",
      desc: "Tabular export of all active openings ready for Excel / Sheets.",
      url: "/api/exports/jobs.csv",
      filename: "goa_active_jobs.csv",
      icon: FileSpreadsheet,
      color: "text-teal-400 bg-teal-500/10 border-teal-500/20",
    },
    {
      title: "Companies CSV",
      desc: "Directory of monitored Goan companies with tech stack & locations.",
      url: "/api/exports/companies.csv",
      filename: "goa_tech_companies.csv",
      icon: FileSpreadsheet,
      color: "text-purple-400 bg-purple-500/10 border-purple-500/20",
    },
    {
      title: "Atom XML RSS Feed",
      desc: "Syndication feed for RSS readers and automated notification bots.",
      url: "/api/feed/jobs.xml",
      filename: "jobs.xml",
      icon: Rss,
      color: "text-orange-400 bg-orange-500/10 border-orange-500/20",
    },
  ];

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl sm:text-3xl font-extrabold text-white flex items-center space-x-2">
          <FileText className="h-7 w-7 text-emerald-400" />
          <span>Intelligence Reports & Exports</span>
        </h1>
        <p className="text-sm text-slate-400 mt-1">
          Download live data in standard open formats or subscribe via Atom RSS syndication.
        </p>
      </div>

      {/* Export Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {downloadLinks.map((item, idx) => {
          const Icon = item.icon;
          return (
            <div
              key={idx}
              className="bg-slate-900/60 border border-slate-800 rounded-2xl p-5 flex flex-col justify-between shadow-lg"
            >
              <div className="space-y-2">
                <div className="flex items-center space-x-3">
                  <div className={`p-2 rounded-xl border ${item.color}`}>
                    <Icon className="h-5 w-5" />
                  </div>
                  <h2 className="font-bold text-white text-sm">{item.title}</h2>
                </div>
                <p className="text-xs text-slate-400">{item.desc}</p>
              </div>

              <div className="pt-4 mt-2">
                <a
                  href={item.url}
                  download={item.filename}
                  className="w-full px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold transition-colors flex items-center justify-center space-x-1.5 border border-slate-700"
                >
                  <Download className="h-3.5 w-3.5 text-emerald-400" />
                  <span>Download File</span>
                </a>
              </div>
            </div>
          );
        })}
      </div>

      {/* Interactive Digest Preview Section */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-3xl p-6 shadow-xl space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-4">
          <div className="flex items-center space-x-2">
            <Eye className="h-5 w-5 text-emerald-400" />
            <h2 className="font-bold text-white text-base">Live Digest Preview</h2>
          </div>

          <div className="flex items-center space-x-2">
            <div className="bg-slate-950 p-1 rounded-xl border border-slate-800 flex text-xs">
              <button
                type="button"
                onClick={() => setActiveTab("md")}
                className={`px-3 py-1 rounded-lg font-medium transition-colors ${
                  activeTab === "md"
                    ? "bg-slate-800 text-emerald-400 shadow"
                    : "text-slate-400 hover:text-white"
                }`}
              >
                Markdown
              </button>
              <button
                type="button"
                onClick={() => setActiveTab("json")}
                className={`px-3 py-1 rounded-lg font-medium transition-colors ${
                  activeTab === "json"
                    ? "bg-slate-800 text-emerald-400 shadow"
                    : "text-slate-400 hover:text-white"
                }`}
              >
                Raw JSON
              </button>
            </div>

            <button
              type="button"
              onClick={handleCopy}
              className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium rounded-lg transition-colors flex items-center space-x-1 border border-slate-700"
            >
              {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
              <span>{copied ? "Copied" : "Copy"}</span>
            </button>
          </div>
        </div>

        {loading ? (
          <div className="py-20 flex justify-center">
            <RefreshCw className="h-8 w-8 text-emerald-400 animate-spin" />
          </div>
        ) : (
          <div className="bg-slate-950 rounded-2xl p-5 border border-slate-800/80 max-h-[500px] overflow-y-auto font-mono text-xs text-slate-300 whitespace-pre-wrap leading-relaxed">
            {activeTab === "md" ? mdContent : jsonContent}
          </div>
        )}
      </div>
    </div>
  );
};
