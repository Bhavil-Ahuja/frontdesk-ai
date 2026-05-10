import React, { useState, useEffect } from 'react';
import {
  Phone,
  CalendarCheck,
  AlertTriangle,
  Clock,
  Activity,
  TrendingUp,
} from 'lucide-react';
import {
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from 'recharts';
import { apiFetch } from '../lib/api';

const OUTCOME_COLORS = {
  BOOKED: '#10b981',
  INQUIRY: '#f59e0b',
  ESCALATED: '#ef4444',
  CANCELLED: '#8b5cf6',
  ABANDONED: '#6b7280',
};

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchStats();
    const interval = setInterval(fetchStats, 30000); // Refresh every 30s
    return () => clearInterval(interval);
  }, []);

  async function fetchStats() {
    try {
      const data = await apiFetch('/api/dashboard/stats');
      setStats(data);
    } catch (err) {
      console.error('Failed to fetch stats:', err);
    } finally {
      setLoading(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500"></div>
      </div>
    );
  }

  if (!stats) {
    return (
      <div className="p-8 text-center text-gray-500">
        Unable to load dashboard data. Is the backend running?
      </div>
    );
  }

  const pieData = Object.entries(stats.outcomes_breakdown)
    .filter(([, v]) => v > 0)
    .map(([name, value]) => ({ name, value }));

  return (
    <div className="p-8 space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Dashboard</h2>
          <p className="text-gray-500 mt-1">Real-time overview of your AI agent</p>
        </div>
        <div className="flex items-center gap-2">
          <div
            className={`w-3 h-3 rounded-full ${
              stats.agent_active ? 'bg-green-400 animate-pulse' : 'bg-red-400'
            }`}
          ></div>
          <span className={`text-sm font-medium ${
            stats.agent_active ? 'text-green-600' : 'text-red-600'
          }`}>
            {stats.agent_active ? 'Agent Active' : 'Agent Offline'}
          </span>
        </div>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatCard
          icon={Phone}
          label="Today's Calls"
          value={stats.today_calls}
          color="blue"
        />
        <StatCard
          icon={CalendarCheck}
          label="Appointments This Week"
          value={stats.week_appointments_booked}
          subtitle="Booked by AI"
          color="green"
        />
        <StatCard
          icon={AlertTriangle}
          label="Escalation Rate"
          value={`${stats.escalation_rate}%`}
          subtitle="Last 30 days"
          color="amber"
        />
        <StatCard
          icon={Clock}
          label="Avg Call Duration"
          value={formatDuration(stats.avg_call_duration)}
          color="purple"
        />
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Calls per day */}
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
            <TrendingUp className="w-5 h-5 text-primary-500" />
            Calls This Week
          </h3>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={stats.calls_per_day}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis dataKey="day" stroke="#94a3b8" fontSize={12} />
              <YAxis stroke="#94a3b8" fontSize={12} allowDecimals={false} />
              <Tooltip
                contentStyle={{
                  borderRadius: '8px',
                  border: '1px solid #e2e8f0',
                  boxShadow: '0 4px 6px -1px rgba(0,0,0,0.1)',
                }}
              />
              <Line
                type="monotone"
                dataKey="count"
                stroke="#14b8a6"
                strokeWidth={3}
                dot={{ r: 5, fill: '#14b8a6' }}
                activeDot={{ r: 7 }}
                name="Calls"
              />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Outcome breakdown */}
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
            <Activity className="w-5 h-5 text-primary-500" />
            Call Outcomes
          </h3>
          {pieData.length > 0 ? (
            <div className="flex items-center gap-6">
              <ResponsiveContainer width="60%" height={260}>
                <PieChart>
                  <Pie
                    data={pieData}
                    cx="50%"
                    cy="50%"
                    innerRadius={60}
                    outerRadius={100}
                    paddingAngle={3}
                    dataKey="value"
                  >
                    {pieData.map((entry) => (
                      <Cell
                        key={entry.name}
                        fill={OUTCOME_COLORS[entry.name] || '#6b7280'}
                      />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
              <div className="space-y-3">
                {pieData.map((entry) => (
                  <div key={entry.name} className="flex items-center gap-2">
                    <div
                      className="w-3 h-3 rounded-full"
                      style={{ backgroundColor: OUTCOME_COLORS[entry.name] }}
                    ></div>
                    <span className="text-sm text-gray-600">
                      {entry.name} ({entry.value})
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-gray-400 text-center py-12">No call data yet</p>
          )}
        </div>
      </div>
    </div>
  );
}

function StatCard({ icon: Icon, label, value, subtitle, color }) {
  const colorMap = {
    blue: 'bg-blue-50 text-blue-600',
    green: 'bg-green-50 text-green-600',
    amber: 'bg-amber-50 text-amber-600',
    purple: 'bg-purple-50 text-purple-600',
  };

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6">
      <div className="flex items-center justify-between">
        <div className={`p-3 rounded-lg ${colorMap[color]}`}>
          <Icon className="w-6 h-6" />
        </div>
      </div>
      <div className="mt-4">
        <p className="text-3xl font-bold text-gray-900">{value}</p>
        <p className="text-sm text-gray-500 mt-1">{label}</p>
        {subtitle && <p className="text-xs text-gray-400 mt-0.5">{subtitle}</p>}
      </div>
    </div>
  );
}

function formatDuration(seconds) {
  if (!seconds) return '0s';
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}
