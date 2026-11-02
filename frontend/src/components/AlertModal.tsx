import React, { useEffect, useRef, useState } from "react";
import { Bell, X, CheckCircle, AlertCircle, Loader2 } from "lucide-react";
import { api } from "../api/client";

interface AlertModalProps {
  isOpen: boolean;
  onClose: () => void;
  defaultTech?: string;
}

export const AlertModal: React.FC<AlertModalProps> = ({ isOpen, onClose, defaultTech }) => {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [email, setEmail] = useState("");
  const [techInput, setTechInput] = useState(defaultTech || "");
  const [locationInput, setLocationInput] = useState("");
  const [ceOnly, setCeOnly] = useState(true);
  const [loading, setLoading] = useState(false);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (isOpen) {
      if (!dialog.open) {
        dialog.showModal();
      }
    } else {
      if (dialog.open) {
        dialog.close();
      }
      setSuccessMsg(null);
      setErrorMsg(null);
    }
  }, [isOpen]);

  // Click outside to close (light dismiss fallback)
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    const handleCancel = (e: Event) => {
      e.preventDefault();
      onClose();
    };

    const handleClickOutside = (e: MouseEvent) => {
      const rect = dialog.getBoundingClientRect();
      const isOutside =
        e.clientX < rect.left ||
        e.clientX > rect.right ||
        e.clientY < rect.top ||
        e.clientY > rect.bottom;
      if (isOutside) {
        onClose();
      }
    };

    dialog.addEventListener("cancel", handleCancel);
    dialog.addEventListener("click", handleClickOutside);
    return () => {
      dialog.removeEventListener("cancel", handleCancel);
      dialog.removeEventListener("click", handleClickOutside);
    };
  }, [onClose]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !email.includes("@")) {
      setErrorMsg("Please enter a valid email address.");
      return;
    }

    setLoading(true);
    setErrorMsg(null);

    const techFilter = techInput
      ? techInput.split(",").map((s) => s.trim()).filter(Boolean)
      : undefined;
    const locationFilter = locationInput
      ? locationInput.split(",").map((s) => s.trim()).filter(Boolean)
      : undefined;

    try {
      await api.subscribeAlert({
        email: email.trim(),
        tech_filter: techFilter,
        location_filter: locationFilter,
        ce_only: ceOnly,
      });
      setSuccessMsg("Subscription confirmed! You will receive email notifications as soon as matching openings are detected.");
      setEmail("");
    } catch (err: any) {
      setErrorMsg(err.message || "Failed to subscribe for alerts.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="alert-modal-title"
      className="bg-slate-900 text-slate-100 rounded-2xl border border-slate-700 shadow-2xl p-0 w-full max-w-md backdrop:bg-black/60 m-auto"
    >
      <div className="p-6 relative">
        <button
          type="button"
          onClick={onClose}
          className="absolute right-4 top-4 p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
          aria-label="Close dialog"
        >
          <X className="h-5 w-5" />
        </button>

        <div className="flex items-center space-x-3 mb-4">
          <div className="h-10 w-10 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 flex items-center justify-center">
            <Bell className="h-5 w-5" />
          </div>
          <div>
            <h2 id="alert-modal-title" className="text-lg font-bold text-white">
              Instant Job Alerts
            </h2>
            <p className="text-xs text-slate-400">
              Get notified when new Goa tech openings match your profile.
            </p>
          </div>
        </div>

        {successMsg ? (
          <div className="py-6 text-center space-y-4">
            <div className="inline-flex p-3 rounded-full bg-emerald-500/10 text-emerald-400">
              <CheckCircle className="h-8 w-8" />
            </div>
            <p className="text-sm text-emerald-300">{successMsg}</p>
            <p className="text-xs text-slate-400">
              Every email contains a 1-click unsubscribe link. Zero spam.
            </p>
            <button
              type="button"
              onClick={onClose}
              className="mt-4 px-4 py-2 bg-slate-800 hover:bg-slate-700 text-white rounded-lg text-sm font-medium transition-colors"
            >
              Done
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            {errorMsg && (
              <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs flex items-center space-x-2">
                <AlertCircle className="h-4 w-4 shrink-0" />
                <span>{errorMsg}</span>
              </div>
            )}

            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                Your Email Address <span className="text-emerald-400">*</span>
              </label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="developer@goa.dev"
                className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                Tech Stack Keywords (Optional, comma-separated)
              </label>
              <input
                type="text"
                value={techInput}
                onChange={(e) => setTechInput(e.target.value)}
                placeholder="Python, React, AWS, Docker"
                className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                Preferred Goa Location (Optional)
              </label>
              <input
                type="text"
                value={locationInput}
                onChange={(e) => setLocationInput(e.target.value)}
                placeholder="Panaji, Verna, Margao"
                className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
              />
            </div>

            <div className="flex items-center space-x-2 pt-1">
              <input
                type="checkbox"
                id="ce-only-check"
                checked={ceOnly}
                onChange={(e) => setCeOnly(e.target.checked)}
                className="rounded bg-slate-950 border-slate-700 text-emerald-500 focus:ring-emerald-500 h-4 w-4"
              />
              <label htmlFor="ce-only-check" className="text-xs text-slate-300 cursor-pointer">
                Only notify for Computer / Software Engineering roles
              </label>
            </div>

            <div className="pt-3 flex justify-end space-x-2 border-t border-slate-800">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 rounded-lg text-sm text-slate-300 hover:bg-slate-800 transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={loading}
                className="px-4 py-2 rounded-lg text-sm font-semibold bg-emerald-500 hover:bg-emerald-600 text-slate-950 transition-colors flex items-center space-x-2 disabled:opacity-50"
              >
                {loading && <Loader2 className="h-4 w-4 animate-spin" />}
                <span>Subscribe Free</span>
              </button>
            </div>
          </form>
        )}
      </div>
    </dialog>
  );
};
