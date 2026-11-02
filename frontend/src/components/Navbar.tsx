import React, { useState, useEffect, useRef } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  Briefcase,
  Building2,
  Cpu,
  FileText,
  Bookmark,
  Scale,
  Menu,
  X,
  Search,
  Landmark,
  Sparkles,
} from "lucide-react";
import { api } from "../api/client";

export const Navbar: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const searchRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setMobileMenuOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (searchQuery.trim().length >= 2) {
      const timer = setTimeout(async () => {
        try {
          const res = await api.getSearchSuggestions(searchQuery.trim());
          setSuggestions(res);
          setShowSuggestions(true);
        } catch {
          setSuggestions([]);
        }
      }, 200);
      return () => clearTimeout(timer);
    } else {
      setSuggestions([]);
      setShowSuggestions(false);
    }
  }, [searchQuery]);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) {
        setShowSuggestions(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchQuery.trim()) {
      setShowSuggestions(false);
      navigate(`/jobs?q=${encodeURIComponent(searchQuery.trim())}`);
    }
  };

  const navItems = [
    { label: "Dashboard", path: "/", icon: Cpu },
    { label: "Companies", path: "/companies", icon: Building2 },
    { label: "Job Board", path: "/jobs", icon: Briefcase },
    { label: "Govt Jobs", path: "/govt-jobs", icon: Landmark },
    { label: "AI Chat", path: "/chat", icon: Sparkles },
    { label: "Reports", path: "/reports", icon: FileText },
    { label: "Compare", path: "/compare", icon: Scale },
    { label: "Saved", path: "/saved", icon: Bookmark },
  ];

  return (
    <header className="sticky top-0 z-40 bg-slate-900/90 backdrop-blur border-b border-slate-800 text-slate-100">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Logo */}
          <Link to="/" className="flex items-center space-x-3 group">
            <div className="h-9 w-9 rounded-xl bg-gradient-to-tr from-emerald-500 to-teal-400 flex items-center justify-center text-slate-950 font-black shadow-md group-hover:scale-105 transition-transform">
              G
            </div>
            <div className="flex flex-col">
              <span className="font-bold text-lg leading-tight tracking-tight text-white group-hover:text-emerald-400 transition-colors">
                Goa<span className="text-emerald-400">IT</span>
              </span>
              <span className="text-[10px] text-slate-400 tracking-wider uppercase font-medium">
                Career Intel
              </span>
            </div>
          </Link>

          {/* Quick Search */}
          <div className="hidden md:flex relative flex-1 max-w-xs mx-6" ref={searchRef}>
            <form onSubmit={handleSearchSubmit} className="w-full relative">
              <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onFocus={() => searchQuery.length >= 2 && setShowSuggestions(true)}
                placeholder="Search jobs, tech, roles..."
                className="w-full bg-slate-950 text-slate-200 text-sm rounded-lg pl-9 pr-4 py-2 border border-slate-700 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 transition-colors"
              />
            </form>
            {showSuggestions && suggestions.length > 0 && (
              <ul className="absolute top-full left-0 right-0 mt-1 bg-slate-900 border border-slate-700 rounded-lg shadow-xl overflow-hidden z-50">
                {suggestions.map((item, idx) => (
                  <li key={idx}>
                    <button
                      type="button"
                      onClick={() => {
                        setSearchQuery(item);
                        setShowSuggestions(false);
                        navigate(`/jobs?q=${encodeURIComponent(item)}`);
                      }}
                      className="w-full text-left px-4 py-2 text-sm text-slate-200 hover:bg-slate-800 hover:text-emerald-400 transition-colors flex items-center space-x-2"
                    >
                      <Search className="h-3.5 w-3.5 text-slate-400" />
                      <span>{item}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Desktop Nav */}
          <nav className="hidden lg:flex items-center space-x-1">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive =
                item.path === "/"
                  ? location.pathname === "/"
                  : location.pathname.startsWith(item.path);
              return (
                <Link
                  key={item.path}
                  to={item.path}
                  className={`px-3 py-2 rounded-lg text-sm font-medium transition-colors flex items-center space-x-1.5 ${
                    isActive
                      ? "bg-slate-800 text-emerald-400 border border-emerald-500/20"
                      : "text-slate-300 hover:text-white hover:bg-slate-800/60"
                  }`}
                >
                  <Icon className="h-4 w-4" />
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </nav>

          {/* Mobile menu button */}
          <div className="flex lg:hidden items-center space-x-2">
            <button
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 focus:outline-none"
              aria-label="Toggle navigation menu"
            >
              {mobileMenuOpen ? <X className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
            </button>
          </div>
        </div>
      </div>

      {/* Mobile Menu Dropdown */}
      {mobileMenuOpen && (
        <div className="lg:hidden border-b border-slate-800 bg-slate-900 px-4 pt-2 pb-4 space-y-1">
          <form onSubmit={handleSearchSubmit} className="mb-3 relative">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search jobs, tech, roles..."
              className="w-full bg-slate-950 text-slate-200 text-sm rounded-lg pl-9 pr-4 py-2 border border-slate-700"
            />
          </form>
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive =
              item.path === "/"
                ? location.pathname === "/"
                : location.pathname.startsWith(item.path);
            return (
              <Link
                key={item.path}
                to={item.path}
                className={`block px-3 py-2 rounded-lg text-base font-medium flex items-center space-x-2 ${
                  isActive
                    ? "bg-slate-800 text-emerald-400 font-semibold"
                    : "text-slate-300 hover:bg-slate-800 hover:text-white"
                }`}
              >
                <Icon className="h-5 w-5" />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </div>
      )}
    </header>
  );
};
