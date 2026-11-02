import React from "react";
import { Routes, Route } from "react-router-dom";
import { Navbar } from "./components/Navbar";
import { Footer } from "./components/Footer";
import { Dashboard } from "./pages/Dashboard";
import { Companies } from "./pages/Companies";
import { CompanyProfile } from "./pages/CompanyProfile";
import { JobBoard } from "./pages/JobBoard";
import { GovtJobs } from "./pages/GovtJobs";
import { AIChat } from "./pages/AIChat";
import { Reports } from "./pages/Reports";
import { Compare } from "./pages/Compare";
import { SavedJobs } from "./pages/SavedJobs";

export const App: React.FC = () => {
  return (
    <div className="min-h-screen flex flex-col bg-slate-950 text-slate-100">
      <Navbar />
      <main className="flex-1 flex flex-col">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/companies" element={<Companies />} />
          <Route path="/company/:name" element={<CompanyProfile />} />
          <Route path="/jobs" element={<JobBoard />} />
          <Route path="/jobs/freshers" element={<JobBoard />} />
          <Route path="/govt-jobs" element={<GovtJobs />} />
          <Route path="/chat" element={<AIChat />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/compare" element={<Compare />} />
          <Route path="/saved" element={<SavedJobs />} />
          <Route path="*" element={<Dashboard />} />
        </Routes>
      </main>
      <Footer />
    </div>
  );
};
export default App;
