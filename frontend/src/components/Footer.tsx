import React from "react";
import { Rss, FileText, Download, ShieldCheck, Heart } from "lucide-react";

export const Footer: React.FC = () => {
  return (
    <footer className="mt-auto border-t border-slate-800 bg-slate-950 text-slate-400 py-8 text-sm">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex flex-col md:flex-row items-center justify-between gap-4">
          {/* Left info */}
          <div className="flex flex-col items-center md:items-start text-center md:text-left">
            <div className="flex items-center space-x-2 text-slate-200 font-semibold">
              <span className="text-emerald-400">GoaIT</span> Career Intelligence
              <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-emerald-950 text-emerald-400 border border-emerald-800">
                <ShieldCheck className="h-3 w-3 mr-1" /> Render Free Tier
              </span>
            </div>
            <p className="text-xs text-slate-500 mt-1">
              Autonomous scraping & career intelligence for Goa's tech ecosystem. Zero AI overhead during ingestion.
            </p>
          </div>

          {/* Quick Feeds & Exports */}
          <div className="flex flex-wrap items-center justify-center gap-4 text-xs font-medium">
            <a
              href="/api/feed/jobs.xml"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-orange-400 border border-slate-800 transition-colors"
            >
              <Rss className="h-3.5 w-3.5" />
              <span>Atom XML Feed</span>
            </a>
            <a
              href="/api/exports/digest.md"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-emerald-400 border border-slate-800 transition-colors"
            >
              <FileText className="h-3.5 w-3.5" />
              <span>Digest MD</span>
            </a>
            <a
              href="/api/exports/jobs.csv"
              download="goa_jobs.csv"
              className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-teal-400 border border-slate-800 transition-colors"
            >
              <Download className="h-3.5 w-3.5" />
              <span>Jobs CSV</span>
            </a>
          </div>
        </div>

        <div className="mt-6 pt-6 border-t border-slate-900 text-center text-xs text-slate-600 flex items-center justify-center space-x-1">
          <span>Built for the Goa Tech & Engineering Community</span>
          <Heart className="h-3.5 w-3.5 text-rose-500 inline fill-rose-500/20" />
        </div>
      </div>
    </footer>
  );
};
