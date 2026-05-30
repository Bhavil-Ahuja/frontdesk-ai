import React, { useState, useEffect } from 'react';
import { Routes, Route, NavLink, Navigate, useNavigate, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
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
  Contact,
  Moon,
  Sun,
  UserCircle,
  HelpCircle,
  Menu,
  X,
} from 'lucide-react';

import Dashboard from './components/Dashboard';
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
import PatientCRM from './components/PatientCRM';
import Profile from './components/Profile';
import SupportTickets from './components/SupportTickets';
import { useAuth } from './contexts/AuthContext';
import { useTheme } from './contexts/ThemeContext';

// ── Tenant nav (always visible to logged-in tenants) ─────────────────────────
// Items with `requireFeature` are hidden when the corresponding feature flag is off.
const TENANT_NAV = [
  { to: '/dashboard', icon: LayoutDashboard, label: 'Overview' },
  { to: '/setup', icon: Rocket, label: 'Setup Guide' },
  { to: '/chat', icon: MessageSquare, label: 'Test Agent' },
  { to: '/patients', icon: Contact, label: 'Patients' },
  { to: '/appointments', icon: CalendarDays, label: 'Appointments' },
  { to: '/providers', icon: Users, label: 'Doctors' },
  { to: '/waitlist', icon: ClipboardList, label: 'Waitlist' },
  { to: '/sms', icon: MessagesSquare, label: 'SMS Messages', requireFeature: 'twilio' },
  { to: '/knowledge', icon: BookOpen, label: 'Practice Info' },
  { to: '/settings', icon: Settings, label: 'Agent Config' },
  { to: '/support', icon: HelpCircle, label: 'Support' },
];


export default function App() {
  const { user, loading, isAuthenticated } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500"></div>
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

// ── Sidebar content (shared between desktop sidebar and mobile drawer) ────────
function SidebarContent({ user, isAdmin, dark, toggleTheme, navigate, location, handleLogout, onNavClick }) {
  return (
    <>
      {/* Logo — clickable, navigates to dashboard */}
      <button
        onClick={() => { navigate(isAdmin ? '/admin/tenants' : '/dashboard'); onNavClick?.(); }}
        className="w-full text-left p-4 md:p-6 border-b border-gray-100 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
      >
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-primary-500 rounded-xl flex items-center justify-center shrink-0">
            <Sparkles className="w-6 h-6 text-white" />
          </div>
          <div className="min-w-0">
            <h1 className="font-bold text-gray-900 dark:text-white text-lg leading-tight truncate">
              {user?.business_name || 'FrontDesk AI'}
            </h1>
            <p className="text-xs text-gray-500 dark:text-gray-400 truncate">
              {isAdmin ? 'Admin · FrontDesk AI' : 'Tenant Dashboard'}
            </p>
          </div>
        </div>
      </button>

      {/* Tenant Navigation (hidden for admin-only users) */}
      {!isAdmin && (
        <nav className="flex-1 p-3 md:p-4 space-y-1 overflow-y-auto">
          {TENANT_NAV.filter(({ requireFeature }) => {
            if (!requireFeature) return true;
            if (requireFeature === 'twilio') return user?.twilio_enabled !== false;
            if (requireFeature === 'vapi') return user?.vapi_enabled !== false;
            return true;
          }).map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              onClick={onNavClick}
              className={({ isActive }) =>
                `flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-300'
                    : 'text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700/50 hover:text-gray-900 dark:hover:text-white'
                }`
              }
            >
              <Icon className="w-5 h-5" />
              {label}
            </NavLink>
          ))}

          {/* Admin section — only visible to admins */}
          {isAdmin && (
            <div className="pt-4 mt-4 border-t border-gray-100 dark:border-gray-700">
              <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider px-4 mb-1">
                Admin
              </p>
              <NavLink
                to="/admin/tenants"
                onClick={onNavClick}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-4 py-2 rounded-lg text-xs font-medium transition-colors ${
                    isActive
                      ? 'bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300'
                      : 'text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700/50 hover:text-gray-900 dark:hover:text-white'
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
        <nav className="flex-1 p-3 md:p-4 space-y-1">
          <NavLink
            to="/admin/tenants"
            onClick={onNavClick}
            className={({ isActive }) =>
              `flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300'
                  : 'text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700/50 hover:text-gray-900 dark:hover:text-white'
              }`
            }
          >
            <Shield className="w-5 h-5" />
            Manage Tenants
          </NavLink>
        </nav>
      )}

      {/* Dark mode toggle + User card + logout */}
      <div className="p-3 md:p-4 border-t border-gray-100 dark:border-gray-700 space-y-2">
        {/* Dark mode toggle */}
        <button
          onClick={toggleTheme}
          className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-600 dark:text-gray-400 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700/50 hover:text-gray-900 dark:hover:text-white transition-colors"
        >
          {dark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
          {dark ? 'Light Mode' : 'Dark Mode'}
        </button>

        {/* User card — clickable, opens profile */}
        <button
          onClick={() => { navigate('/profile'); onNavClick?.(); }}
          className={`w-full flex items-center gap-3 px-2 py-2 rounded-lg transition-colors ${
            location.pathname === '/profile'
              ? 'bg-primary-50 dark:bg-primary-900/30'
              : 'hover:bg-gray-50 dark:hover:bg-gray-700/50'
          }`}
        >
          <div className="w-8 h-8 bg-primary-100 dark:bg-primary-900/50 text-primary-700 dark:text-primary-300 rounded-full flex items-center justify-center text-xs font-semibold shrink-0">
            {(user?.name || user?.email || '?').charAt(0).toUpperCase()}
          </div>
          <div className="min-w-0 flex-1 text-left">
            <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
              {user?.name || 'Account'}
            </p>
            <p className="text-xs text-gray-500 dark:text-gray-400 truncate">{user?.email}</p>
          </div>
          <UserCircle className="w-4 h-4 text-gray-400 shrink-0" />
        </button>

        <button
          onClick={() => { handleLogout(); onNavClick?.(); }}
          className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-600 dark:text-gray-400 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700/50 hover:text-gray-900 dark:hover:text-white transition-colors"
        >
          <LogOut className="w-4 h-4" />
          Sign out
        </button>
      </div>
    </>
  );
}

// ── App shell (sidebar + main content for authenticated users) ───────────────
function AppShell() {
  const { user, logout, isAdmin } = useAuth();
  const { dark, toggle: toggleTheme } = useTheme();
  const navigate = useNavigate();
  const location = useLocation();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // Close sidebar on route change (mobile)
  useEffect(() => {
    setSidebarOpen(false);
  }, [location.pathname]);

  function handleLogout() {
    logout();
    navigate('/login', { replace: true });
  }

  const sidebarProps = {
    user, isAdmin, dark, toggleTheme, navigate, location, handleLogout,
    onNavClick: () => setSidebarOpen(false),
  };

  return (
    <div className="flex h-screen bg-gray-50 dark:bg-gray-900">
      {/* ── Mobile top bar ──────────────────────────────────────────── */}
      <div className="fixed top-0 left-0 right-0 z-30 md:hidden bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-4 py-3 flex items-center justify-between">
        <button
          onClick={() => setSidebarOpen(true)}
          className="p-2 -ml-2 rounded-lg text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
          aria-label="Open menu"
        >
          <Menu className="w-6 h-6" />
        </button>
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 bg-primary-500 rounded-lg flex items-center justify-center">
            <Sparkles className="w-4 h-4 text-white" />
          </div>
          <span className="font-bold text-gray-900 dark:text-white text-sm truncate max-w-[180px]">
            {user?.business_name || 'FrontDesk AI'}
          </span>
        </div>
        <button
          onClick={() => navigate('/profile')}
          className="p-2 -mr-2 rounded-lg text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
          aria-label="Profile"
        >
          <UserCircle className="w-6 h-6" />
        </button>
      </div>

      {/* ── Mobile sidebar drawer overlay ───────────────────────────── */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/40 z-40 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* ── Mobile sidebar drawer ──────────────────────────────────── */}
      <aside
        className={`fixed inset-y-0 left-0 z-50 w-72 bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700 flex flex-col transform transition-transform duration-200 ease-in-out md:hidden ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {/* Close button */}
        <div className="absolute top-3 right-3">
          <button
            onClick={() => setSidebarOpen(false)}
            className="p-2 rounded-lg text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
        <SidebarContent {...sidebarProps} />
      </aside>

      {/* ── Desktop sidebar (always visible) ───────────────────────── */}
      <aside className="hidden md:flex w-64 bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700 flex-col shrink-0">
        <SidebarContent {...sidebarProps} />
      </aside>

      {/* Main content — add top padding on mobile for the fixed header */}
      <main className="flex-1 overflow-y-auto bg-gray-50 dark:bg-gray-900 pt-[60px] md:pt-0">
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
          {/* Test Agent chat — always available for testing the LLM + tools pipeline */}
          <Route
            path="/chat"
            element={
              <ProtectedRoute>
                <LocalChat />
              </ProtectedRoute>
            }
          />
          <Route
            path="/patients"
            element={
              <ProtectedRoute>
                <PatientCRM />
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
          <Route
            path="/support"
            element={
              <ProtectedRoute>
                <SupportTickets />
              </ProtectedRoute>
            }
          />
          <Route
            path="/profile"
            element={
              <ProtectedRoute>
                <Profile />
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
