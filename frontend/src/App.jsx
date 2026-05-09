import React, { useEffect, useState } from 'react';
import { Routes, Route, NavLink, Navigate, useNavigate, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  Phone,
  CalendarDays,
  BookOpen,
  Settings,
  Sparkles,
  Shield,
  LogOut,
  Rocket,
  MessageSquare,
  Users,
  ClipboardList,
  MessagesSquare,
} from 'lucide-react';

import Dashboard from './components/Dashboard';
import CallLogs from './components/CallLogs';
import AppointmentManager from './components/AppointmentManager';
import KnowledgeBase from './components/KnowledgeBase';
import AgentConfig from './components/AgentConfig';
import TenantRegister from './components/TenantRegister';
import TenantAdmin from './components/TenantAdmin';
import Landing from './components/Landing';
import Login from './components/Login';
import PendingApproval from './components/PendingApproval';
import SetupGuide from './components/SetupGuide';
import LocalChat from './components/LocalChat';
import ProtectedRoute from './components/ProtectedRoute';
import ProviderManager from './components/ProviderManager';
import WaitlistView from './components/WaitlistView';
import SMSConversations from './components/SMSConversations';
import { useAuth } from './contexts/AuthContext';

// ── Tenant nav (always visible to logged-in tenants) ─────────────────────────
// `chatOnly` items are only included when LOCAL_CHAT_MODE is on (server flag).
const TENANT_NAV = [
  { to: '/dashboard', icon: LayoutDashboard, label: 'Overview' },
  { to: '/setup', icon: Rocket, label: 'Setup Guide' },
  { to: '/chat', icon: MessageSquare, label: 'Test Agent', chatOnly: true },
  { to: '/calls', icon: Phone, label: 'Call Logs' },
  { to: '/appointments', icon: CalendarDays, label: 'Appointments' },
  { to: '/providers', icon: Users, label: 'Providers' },
  { to: '/waitlist', icon: ClipboardList, label: 'Waitlist' },
  { to: '/sms', icon: MessagesSquare, label: 'SMS Messages' },
  { to: '/knowledge', icon: BookOpen, label: 'Knowledge Base' },
  { to: '/settings', icon: Settings, label: 'Agent Config' },
];

// ── Hook: ask the backend whether local chat mode is enabled ─────────────────
function useLocalChatEnabled() {
  const [enabled, setEnabled] = useState(false);
  useEffect(() => {
    let cancelled = false;
    fetch('/api/chat/enabled')
      .then((r) => (r.ok ? r.json() : { enabled: false }))
      .then((data) => {
        if (!cancelled) setEnabled(!!data?.enabled);
      })
      .catch(() => {
        if (!cancelled) setEnabled(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return enabled;
}

export default function App() {
  const { user, loading, isAuthenticated } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-dental-500"></div>
      </div>
    );
  }

  return (
    <Routes>
      {/* ── Public routes (no sidebar / no auth required) ───────────────── */}
      <Route
        path="/"
        element={isAuthenticated ? <Navigate to={user?.is_admin ? '/admin/tenants' : '/dashboard'} replace /> : <Landing />}
      />
      <Route
        path="/login"
        element={isAuthenticated ? <Navigate to={user?.is_admin ? '/admin/tenants' : '/dashboard'} replace /> : <Login />}
      />
      <Route
        path="/register"
        element={isAuthenticated ? <Navigate to="/dashboard" replace /> : <TenantRegister />}
      />
      <Route
        path="/pending"
        element={
          <ProtectedRoute requireActive={false}>
            <PendingApproval />
          </ProtectedRoute>
        }
      />

      {/* ── Authenticated app shell with sidebar ────────────────────────── */}
      <Route
        path="/*"
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      />
    </Routes>
  );
}

// ── App shell (sidebar + main content for authenticated users) ───────────────
function AppShell() {
  const { user, logout, isAdmin } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const localChatEnabled = useLocalChatEnabled();

  function handleLogout() {
    logout();
    navigate('/login', { replace: true });
  }

  return (
    <div className="flex h-screen bg-gray-50">
      {/* Sidebar */}
      <aside className="w-64 bg-white border-r border-gray-200 flex flex-col">
        {/* Logo */}
        <div className="p-6 border-b border-gray-100">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-dental-500 rounded-xl flex items-center justify-center">
              <Sparkles className="w-6 h-6 text-white" />
            </div>
            <div className="min-w-0">
              <h1 className="font-bold text-gray-900 text-lg leading-tight truncate">
                {user?.business_name || 'Scheduler.ai'}
              </h1>
              <p className="text-xs text-gray-500 truncate">
                {isAdmin ? 'Admin · Scheduler.ai' : 'Tenant Dashboard'}
              </p>
            </div>
          </div>
        </div>

        {/* Tenant Navigation (hidden for admin-only users) */}
        {!isAdmin && (
          <nav className="flex-1 p-4 space-y-1 overflow-y-auto">
            {TENANT_NAV.filter((item) => !item.chatOnly || localChatEnabled).map(({ to, icon: Icon, label }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-colors ${
                    isActive
                      ? 'bg-dental-50 text-dental-700'
                      : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                  }`
                }
              >
                <Icon className="w-5 h-5" />
                {label}
              </NavLink>
            ))}

            {/* Admin section — only visible to admins */}
            {isAdmin && (
              <div className="pt-4 mt-4 border-t border-gray-100">
                <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider px-4 mb-1">
                  Admin
                </p>
                <NavLink
                  to="/admin/tenants"
                  className={({ isActive }) =>
                    `flex items-center gap-3 px-4 py-2 rounded-lg text-xs font-medium transition-colors ${
                      isActive
                        ? 'bg-amber-50 text-amber-700'
                        : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'
                    }`
                  }
                >
                  <Shield className="w-4 h-4" />
                  Tenants
                </NavLink>
              </div>
            )}
          </nav>
        )}

        {/* Admin nav (admin-only users) */}
        {isAdmin && (
          <nav className="flex-1 p-4 space-y-1">
            <NavLink
              to="/admin/tenants"
              className={({ isActive }) =>
                `flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-amber-50 text-amber-700'
                    : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                }`
              }
            >
              <Shield className="w-5 h-5" />
              Manage Tenants
            </NavLink>
          </nav>
        )}

        {/* User card + logout */}
        <div className="p-4 border-t border-gray-100">
          <div className="flex items-center gap-3 px-2 py-2 mb-2">
            <div className="w-8 h-8 bg-dental-100 text-dental-700 rounded-full flex items-center justify-center text-xs font-semibold shrink-0">
              {(user?.owner_name || user?.email || '?').charAt(0).toUpperCase()}
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-gray-900 truncate">
                {user?.owner_name || 'Account'}
              </p>
              <p className="text-xs text-gray-500 truncate">{user?.email}</p>
            </div>
          </div>
          <button
            onClick={handleLogout}
            className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-600 rounded-lg hover:bg-gray-50 hover:text-gray-900 transition-colors"
          >
            <LogOut className="w-4 h-4" />
            Sign out
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        <Routes>
          {/* Tenant routes */}
          <Route
            path="/dashboard"
            element={
              <ProtectedRoute>
                <Dashboard />
              </ProtectedRoute>
            }
          />
          <Route
            path="/setup"
            element={
              <ProtectedRoute>
                <SetupGuide />
              </ProtectedRoute>
            }
          />
          {/* Local chat — only mounted when the backend flag is on. When off,
              navigating to /chat falls through to the catch-all redirect. */}
          {localChatEnabled && (
            <Route
              path="/chat"
              element={
                <ProtectedRoute>
                  <LocalChat />
                </ProtectedRoute>
              }
            />
          )}
          <Route
            path="/calls"
            element={
              <ProtectedRoute>
                <CallLogs />
              </ProtectedRoute>
            }
          />
          <Route
            path="/appointments"
            element={
              <ProtectedRoute>
                <AppointmentManager />
              </ProtectedRoute>
            }
          />
          <Route
            path="/providers"
            element={
              <ProtectedRoute>
                <ProviderManager />
              </ProtectedRoute>
            }
          />
          <Route
            path="/waitlist"
            element={
              <ProtectedRoute>
                <WaitlistView />
              </ProtectedRoute>
            }
          />
          <Route
            path="/sms"
            element={
              <ProtectedRoute>
                <SMSConversations />
              </ProtectedRoute>
            }
          />
          <Route
            path="/knowledge"
            element={
              <ProtectedRoute>
                <KnowledgeBase />
              </ProtectedRoute>
            }
          />
          <Route
            path="/settings"
            element={
              <ProtectedRoute>
                <AgentConfig />
              </ProtectedRoute>
            }
          />

          {/* Admin routes */}
          <Route
            path="/admin/tenants"
            element={
              <ProtectedRoute requireAdmin requireActive={false}>
                <TenantAdmin />
              </ProtectedRoute>
            }
          />

          {/* Fallback inside the shell */}
          <Route path="*" element={<Navigate to={isAdmin ? '/admin/tenants' : '/dashboard'} replace />} />
        </Routes>
      </main>
    </div>
  );
}
