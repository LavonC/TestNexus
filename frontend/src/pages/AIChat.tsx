import React, { useState, useEffect, useRef } from "react";
import {
  Sparkles,
  Send,
  Key,
  Bot,
  User,
  RefreshCw,
  Trash2,
  CheckCircle,
  HelpCircle,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { api } from "../api/client";
import { ChatMessage } from "../types";

export const AIChat: React.FC = () => {
  const [messages, setMessages] = useState<ChatMessage[]>(() => {
    try {
      const saved = localStorage.getItem("goait_chat_history");
      if (saved) return JSON.parse(saved);
    } catch {
      // ignore
    }
    return [
      {
        id: "intro",
        role: "assistant",
        content:
          "Hello! I am your **GoaIT Career Assistant**, grounded directly in the live Goa tech companies and job openings database.\n\nAsk me anything about hiring companies, required tech stacks, salary/experience levels, or government IT circulars!",
        source: "system",
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      },
    ];
  });

  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [userApiKey, setUserApiKey] = useState(
    () => localStorage.getItem("goait_user_gemini_key") || ""
  );
  const [selectedModel, setSelectedModel] = useState(
    () => localStorage.getItem("goait_user_model") || "gemini-3.8-flash"
  );
  const [showSettings, setShowSettings] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try {
      localStorage.setItem("goait_chat_history", JSON.stringify(messages));
    } catch {
      // ignore
    }
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleKeySave = (key: string) => {
    setUserApiKey(key);
    localStorage.setItem("goait_user_gemini_key", key.trim());
  };

  const handleModelChange = (model: string) => {
    setSelectedModel(model);
    localStorage.setItem("goait_user_model", model);
  };

  const clearChat = () => {
    const initial: ChatMessage[] = [
      {
        id: "intro-cleared",
        role: "assistant",
        content:
          "Chat history cleared. How can I assist you with the Goa tech ecosystem today?",
        source: "system",
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      },
    ];
    setMessages(initial);
    localStorage.removeItem("goait_chat_history");
  };

  const handleSend = async (questionText?: string) => {
    const q = (questionText || input).trim();
    if (!q || loading) return;

    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: q,
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    try {
      const res = await api.sendChat(q, userApiKey, selectedModel);
      const assistantMsg: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        content: res.answer,
        source: (res.source as any) || "gemini_server",
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err: any) {
      const errorMsg: ChatMessage = {
        id: `err-${Date.now()}`,
        role: "assistant",
        content: `Error: ${err.message || "Could not process request."}`,
        source: "system",
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setLoading(false);
    }
  };

  const suggestedPrompts = [
    "Which Goa companies are actively hiring Python developers?",
    "Show fresher openings in Panaji and Verna",
    "What government IT vacancies have upcoming deadlines?",
    "Compare Spintly and Codemax tech stacks",
    "What are the top 5 most demanded skills in Goa right now?",
  ];

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8 flex flex-col h-[calc(100vh-8rem)]">
      {/* Header */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 mb-4 flex items-center justify-between shadow-lg">
        <div className="flex items-center space-x-3">
          <div className="h-10 w-10 rounded-xl bg-gradient-to-tr from-emerald-500 to-teal-400 flex items-center justify-center text-slate-950 shadow-md">
            <Sparkles className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-base font-bold text-white flex items-center space-x-2">
              <span>GoaIT Grounded Career Assistant</span>
            </h1>
            <p className="text-xs text-slate-400">
              3-Tier AI Q&A: User Key → Server Gemini → 100% Offline DB Fallback
            </p>
          </div>
        </div>

        <div className="flex items-center space-x-2">
          <button
            type="button"
            onClick={() => setShowSettings(!showSettings)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors flex items-center space-x-1.5 ${
              userApiKey
                ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
                : "bg-slate-800 text-slate-300 border-slate-700 hover:text-white"
            }`}
          >
            <Key className="h-3.5 w-3.5" />
            <span>{userApiKey ? "Key Configured" : "Add Gemini Key"}</span>
            {showSettings ? (
              <ChevronUp className="h-3.5 w-3.5" />
            ) : (
              <ChevronDown className="h-3.5 w-3.5" />
            )}
          </button>

          <button
            type="button"
            onClick={clearChat}
            className="p-1.5 rounded-lg text-slate-400 hover:text-rose-400 hover:bg-slate-800 transition-colors"
            title="Clear Chat History"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Settings Drawer */}
      {showSettings && (
        <div className="bg-slate-900/90 border border-slate-700 rounded-2xl p-4 mb-4 text-xs space-y-3">
          <div className="flex items-center justify-between">
            <div className="font-semibold text-white flex items-center space-x-1.5">
              <Key className="h-4 w-4 text-emerald-400" />
              <span>Personal Gemini API Key (Optional)</span>
            </div>
            <a
              href="https://aistudio.google.com/app/apikey"
              target="_blank"
              rel="noopener noreferrer"
              className="text-emerald-400 hover:underline"
            >
              Get Free Key from Google AI Studio →
            </a>
          </div>
          <p className="text-slate-400">
            Supplying your own key gives you 1,500 requests/day directly through Google's free tier.
            Your key stays in your browser's local storage and is only transmitted over HTTPS with your questions.
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-1">
            <div className="sm:col-span-2">
              <input
                type="password"
                value={userApiKey}
                onChange={(e) => handleKeySave(e.target.value)}
                placeholder="AIzaSy..."
                className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-white font-mono placeholder-slate-600 focus:outline-none focus:border-emerald-500"
              />
            </div>

            <div>
              <select
                value={selectedModel}
                onChange={(e) => handleModelChange(e.target.value)}
                className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-emerald-500"
              >
                <option value="gemini-3.8-flash">gemini-3.8-flash (Recommended)</option>
                <option value="gemini-3.5-flash">gemini-3.5-flash (Fast)</option>
                <option value="gemini-3.5-flash-lite">gemini-3.5-flash-lite (Light)</option>
              </select>
            </div>
          </div>
        </div>
      )}

      {/* Messages Scroll Area */}
      <div className="flex-1 overflow-y-auto bg-slate-950/60 border border-slate-800 rounded-2xl p-4 space-y-4 mb-4">
        {messages.map((msg) => {
          const isUser = msg.role === "user";
          return (
            <div
              key={msg.id}
              className={`flex items-start space-x-3 ${isUser ? "flex-row-reverse space-x-reverse" : ""}`}
            >
              <div
                className={`h-8 w-8 rounded-xl flex items-center justify-center shrink-0 ${
                  isUser
                    ? "bg-slate-800 text-slate-300"
                    : "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                }`}
              >
                {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
              </div>

              <div className={`space-y-1.5 max-w-[85%] ${isUser ? "text-right" : ""}`}>
                <div
                  className={`inline-block text-left p-4 rounded-2xl text-sm leading-relaxed ${
                    isUser
                      ? "bg-emerald-600 text-slate-950 font-medium rounded-tr-sm"
                      : "bg-slate-900 border border-slate-800 text-slate-200 rounded-tl-sm shadow-md"
                  }`}
                >
                  <div className="whitespace-pre-wrap">{msg.content}</div>
                </div>

                {/* Metadata & Source badge */}
                <div className="flex items-center space-x-2 text-[10px] text-slate-500 px-1">
                  <span>{msg.timestamp}</span>
                  {msg.source && msg.source !== "system" && (
                    <span
                      className={`px-1.5 py-0.2 rounded font-medium ${
                        msg.source === "gemini_user"
                          ? "bg-emerald-950 text-emerald-400 border border-emerald-800"
                          : msg.source === "offline_db"
                          ? "bg-purple-950 text-purple-400 border border-purple-800"
                          : "bg-blue-950 text-blue-400 border border-blue-800"
                      }`}
                    >
                      {msg.source === "gemini_user"
                        ? "User Key"
                        : msg.source === "offline_db"
                        ? "Offline DB Search"
                        : "Server Gemini"}
                    </span>
                  )}
                </div>
              </div>
            </div>
          );
        })}

        {loading && (
          <div className="flex items-start space-x-3">
            <div className="h-8 w-8 rounded-xl bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center justify-center">
              <Bot className="h-4 w-4" />
            </div>
            <div className="p-4 rounded-2xl bg-slate-900 border border-slate-800 text-slate-400 text-xs flex items-center space-x-2">
              <RefreshCw className="h-4 w-4 animate-spin text-emerald-400" />
              <span>Analyzing database and formulating grounded response...</span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Suggested Prompt Chips */}
      {messages.length <= 2 && (
        <div className="flex flex-wrap gap-2 mb-3">
          {suggestedPrompts.map((prompt, idx) => (
            <button
              key={idx}
              type="button"
              onClick={() => handleSend(prompt)}
              className="text-xs px-3 py-1.5 rounded-full bg-slate-900 hover:bg-slate-800 text-slate-300 hover:text-emerald-300 border border-slate-800 hover:border-slate-700 transition-colors"
            >
              {prompt}
            </button>
          ))}
        </div>
      )}

      {/* Input Bar */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          handleSend();
        }}
        className="flex items-center space-x-2"
      >
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a question about Goa tech jobs or companies..."
          disabled={loading}
          className="flex-1 bg-slate-900 border border-slate-700 rounded-xl px-4 py-3 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={!input.trim() || loading}
          className="p-3 bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-bold rounded-xl transition-colors disabled:opacity-40 disabled:cursor-not-allowed shadow-md"
          aria-label="Send message"
        >
          <Send className="h-5 w-5" />
        </button>
      </form>
    </div>
  );
};
