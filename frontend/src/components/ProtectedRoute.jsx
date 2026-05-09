import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

/**
 * ProtectedRoute — guards routes based on auth state.
 *
 * Usage:
 *   <ProtectedRoute>...</ProtectedRoute>             — requires login
 *   <ProtectedRoute requireAdmin>...</ProtectedRoute> — requires admin
 *   <ProtectedRoute requireActive>...</ProtectedRoute> — requires ACTIVE status
 */
export default function ProtectedRoute({ children, requireAdmin = false, requireActive = true }) {
  const { user, loading, isAuthenticated, isAdmin, isPending } = useAuth();
  const location = useLocation();

  // Wait for initial /auth/me load
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-dental-500"></div>
      </div>
    );
  }

  // Not logged in → /login (preserve where they came from)
  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  // Pending users → /pending (admins skip this since they're auto-active)
  if (requireActive && isPending && !isAdmin) {
    return <Navigate to="/pending" replace />;
  }

  // Admin gate
  if (requireAdmin && !isAdmin) {
    return <Navigate to="/" replace />;
  }

  // Suspended/deactivated → kick to login
  if (user && (user.status === 'SUSPENDED' || user.status === 'DEACTIVATED') && !isAdmin) {
    return <Navigate to="/login" replace />;
  }

  return children;
}
