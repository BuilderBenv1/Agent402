"use client";

import { useEffect, useState } from "react";
import { Trophy, ArrowUpRight, Filter, Globe } from "lucide-react";
import type { TrustedAgent, NetworkStats } from "@/lib/api";
import { getScoreColor, getTierColor, TIER_ORDER } from "@/lib/constants";

const API = process.env.NEXT_PUBLIC_API_URL || "https://api.agent402.io";

const TIER_ICONS: Record<string, string> = {
  diamond: "\u{1F48E}",
  platinum: "\u{2B50}",
  gold: "\u{1F3C6}",
  silver: "\u{1FA99}",
  bronze: "\u{1F949}",
  unranked: "\u{2796}",
};

const CHAINS = [
  { slug: "", label: "All Chains" },
  { slug: "avalanche", label: "Avalanche" },
  { slug: "ethereum", label: "Ethereum" },
  { slug: "base", label: "Base" },
  { slug: "polygon", label: "Polygon" },
];

const CHAIN_COLORS: Record<string, string> = {
  avalanche: "text-red-400",
  ethereum: "text-blue-400",
  base: "text-blue-300",
  polygon: "text-purple-400",
  solana: "text-purple-400",
};

const CATEGORIES = [
  { slug: "", label: "All" },
  { slug: "defi", label: "DeFi" },
  { slug: "gaming", label: "Gaming" },
  { slug: "rwa", label: "RWA" },
  { slug: "payments", label: "Payments" },
  { slug: "data", label: "Data" },
  { slug: "general", label: "General" },
];

function ScoreBar({ score }: { score: number }) {
  return (
    <div className="flex items-center gap-2">
      <span className={`font-bold font-mono text-sm ${getScoreColor(score)}`}>
        {score.toFixed(1)}
      </span>
      <div className="w-16 bg-surface-2 rounded-full h-1.5 hidden md:block">
        <div
          className={`h-1.5 rounded-full transition-all ${
            score >= 80 ? "bg-success" :
            score >= 60 ? "bg-primary" :
            score >= 40 ? "bg-warning" : "bg-danger"
          }`}
          style={{ width: `${Math.min(100, score)}%` }}
        />
      </div>
    </div>
  );
}

export default function LeaderboardPage() {
  const [agents, setAgents] = useState<TrustedAgent[]>([]);
  const [stats, setStats] = useState<NetworkStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [category, setCategory] = useState("");
  const [chain, setChain] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(`${API}/api/v1/network/stats`)
      .then((r) => (r.ok ? r.json() : null))
      .then(setStats)
      .catch(() => {});
  }, []);

  useEffect(() => {
    setLoading(true);
    const params = new URLSearchParams({ limit: "50" });
    if (category) params.set("category", category);
    if (chain) params.set("chain", chain);

    fetch(`${API}/api/v1/agents/top?${params}`)
      .then((r) => {
        if (r.status === 402) {
          setError("Paid endpoint \u2014 use x402 SDK");
          return [];
        }
        return r.ok ? r.json() : [];
      })
      .then((data) => {
        if (Array.isArray(data)) setAgents(data);
      })
      .catch(() => setError("Failed to load"))
      .finally(() => setLoading(false));
  }, [category, chain]);

  return (
    <div className="max-w-5xl mx-auto px-4 py-12">
      <div className="text-center mb-10">
        <div className="flex items-center justify-center gap-2 mb-2">
          <Trophy className="w-6 h-6 text-primary" />
          <h1 className="font-sans text-3xl font-bold text-white">
            Leaderboard
          </h1>
        </div>
        <p className="text-muted">
          Top-rated AI agents by composite trust score
        </p>
      </div>

      {/* Tier Distribution Bar */}
      {stats?.tier_distribution && Object.keys(stats.tier_distribution).length > 0 && (
        <div className="bg-surface border border-surface-2 rounded-xl p-4 mb-6">
          <div className="flex rounded-lg overflow-hidden h-4 mb-3">
            {TIER_ORDER.map((tier) => {
              const count = stats.tier_distribution[tier] || 0;
              const pct = stats.total_agents > 0 ? (count / stats.total_agents) * 100 : 0;
              if (pct === 0) return null;
              const colors: Record<string, string> = {
                diamond: "bg-cyan-500", platinum: "bg-violet-500", gold: "bg-yellow-500",
                silver: "bg-gray-400", bronze: "bg-orange-500", unranked: "bg-gray-700",
              };
              return (
                <div
                  key={tier}
                  className={`${colors[tier]} transition-all`}
                  style={{ width: `${pct}%` }}
                  title={`${tier}: ${count.toLocaleString()} (${pct.toFixed(1)}%)`}
                />
              );
            })}
          </div>
          <div className="flex flex-wrap gap-3 justify-center text-xs">
            {TIER_ORDER.map((tier) => {
              const count = stats.tier_distribution[tier] || 0;
              if (count === 0) return null;
              const dotColors: Record<string, string> = {
                diamond: "bg-cyan-500", platinum: "bg-violet-500", gold: "bg-yellow-500",
                silver: "bg-gray-400", bronze: "bg-orange-500", unranked: "bg-gray-700",
              };
              return (
                <div key={tier} className="flex items-center gap-1.5">
                  <div className={`w-2 h-2 rounded-full ${dotColors[tier]}`} />
                  <span className="text-muted capitalize">{tier}</span>
                  <span className="text-white font-mono">{count.toLocaleString()}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Chain filters */}
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <Globe className="w-4 h-4 text-muted-3" />
        {CHAINS.map((c) => {
          const count = stats?.chain_distribution?.[c.slug] || 0;
          return (
            <button
              key={c.slug}
              onClick={() => setChain(c.slug)}
              className={`text-xs px-3 py-1.5 rounded-lg font-mono transition-colors flex items-center gap-1.5 ${
                chain === c.slug
                  ? "bg-primary text-white"
                  : "bg-surface border border-surface-2 text-muted hover:text-white hover:border-primary/30"
              }`}
            >
              {c.label}
              {c.slug && count > 0 && (
                <span className={`text-[10px] ${chain === c.slug ? "text-white/70" : "text-muted-3"}`}>
                  {count.toLocaleString()}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Category filters */}
      <div className="flex items-center gap-2 mb-6 flex-wrap">
        <Filter className="w-4 h-4 text-muted-3" />
        {CATEGORIES.map((cat) => {
          const count = stats?.category_counts?.[cat.slug] || 0;
          return (
            <button
              key={cat.slug}
              onClick={() => setCategory(cat.slug)}
              className={`text-xs px-3 py-1.5 rounded-lg font-mono transition-colors flex items-center gap-1.5 ${
                category === cat.slug
                  ? "bg-primary text-white"
                  : "bg-surface border border-surface-2 text-muted hover:text-white hover:border-primary/30"
              }`}
            >
              {cat.label}
              {cat.slug && count > 0 && (
                <span className={`text-[10px] ${category === cat.slug ? "text-white/70" : "text-muted-3"}`}>
                  {count.toLocaleString()}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Error state */}
      {error && (
        <div className="bg-danger/10 border border-danger/20 rounded-lg p-4 text-sm text-danger mb-6">
          {error}
        </div>
      )}

      {/* Table */}
      <div className="bg-surface border border-surface-2 rounded-xl overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-surface-2 text-xs text-muted-2 uppercase tracking-wider">
              <th className="text-left px-4 py-3 w-12">#</th>
              <th className="text-left px-4 py-3">Agent</th>
              <th className="text-left px-4 py-3 hidden md:table-cell">Category</th>
              <th className="text-left px-4 py-3">Tier</th>
              <th className="text-right px-4 py-3">Score</th>
              <th className="text-right px-4 py-3 hidden md:table-cell">Feedback</th>
              <th className="text-right px-4 py-3 w-10"></th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={7} className="text-center py-12 text-muted">
                  Loading...
                </td>
              </tr>
            ) : agents.length === 0 ? (
              <tr>
                <td colSpan={7} className="text-center py-12 text-muted">
                  No agents found
                </td>
              </tr>
            ) : (
              agents.map((agent, i) => (
                <tr
                  key={agent.agent_id}
                  className="border-b border-surface-2/50 hover:bg-surface-2/30 transition-colors"
                >
                  <td className="px-4 py-3 text-muted-2 font-mono text-sm">
                    {i + 1}
                  </td>
                  <td className="px-4 py-3">
                    <div className="font-semibold text-white text-sm">
                      {agent.name || `Agent #${agent.agent_id}`}
                    </div>
                    <div className="text-xs text-muted-3 font-mono flex items-center gap-1.5">
                      #{agent.agent_id}
                      <span className={`capitalize ${CHAIN_COLORS[agent.chain] || "text-muted-3"}`}>
                        {agent.chain}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-3 hidden md:table-cell">
                    <span className="text-xs text-muted font-mono">
                      {agent.category || "\u2014"}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`text-xs px-2 py-0.5 rounded border font-mono uppercase inline-flex items-center gap-1 ${getTierColor(
                        agent.tier
                      )}`}
                    >
                      <span>{TIER_ICONS[agent.tier] || ""}</span>
                      {agent.tier}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <ScoreBar score={agent.composite_score} />
                  </td>
                  <td className="px-4 py-3 text-right hidden md:table-cell text-sm text-muted">
                    {agent.feedback_count}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <a
                      href={`/lookup?id=${agent.agent_id}`}
                      className="text-primary hover:text-primary-light"
                    >
                      <ArrowUpRight className="w-4 h-4" />
                    </a>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
