import React, { useState, useEffect } from 'react';
import {
  CalendarCheck,
  AlertTriangle,
} from 'lucide-react';
import { apiFetch } from '../lib/api';

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
      <div className="p-8 text-center text-gray-500 dark:text-gray-400">
        Unable to load dashboard data. Is the backend running?
      </div>
    );
  }

  return (
    <div className="p-4 md:p-8 space-y-6 md:space-y-8">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-xl md:text-2xl font-bold text-gray-900 dark:text-white">Dashboard</h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">Real-time overview of your AI agent</p>
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
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
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
      </div>
    </div>
  );
}

function StatCard({ icon: Icon, label, value, subtitle, color }) {
  const colorMap = {
    blue: 'bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400',
    green: 'bg-green-50 text-green-600 dark:bg-green-900/30 dark:text-green-400',
    amber: 'bg-amber-50 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400',
    purple: 'bg-purple-50 text-purple-600 dark:bg-purple-900/30 dark:text-purple-400',
  };

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
      <div className="flex items-center justify-between">
        <div className={`p-3 rounded-lg ${colorMap[color]}`}>
          <Icon className="w-6 h-6" />
        </div>
      </div>
      <div className="mt-4">
        <p className="text-3xl font-bold text-gray-900 dark:text-white">{value}</p>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">{label}</p>
        {subtitle && <p className="text-xs text-gray-400 mt-0.5">{subtitle}</p>}
      </div>
    </div>
  );
}

