import React, { useEffect } from 'react';
import { Clock, LogOut, RefreshCw, Mail, Sparkles } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { useNavigate } from 'react-router-dom';

export default function PendingApproval() {
  const { user, logout, refreshUser } = useAuth();
  const navigate = useNavigate();

  // Auto-refresh every 30 seconds in case admin approves
  useEffect(() => {
    const tick = async () => {
      const updated = await refreshUser();
      if (updated && updated.status === 'ACTIVE') {
        navigate('/', { replace: true });
      }
    };
    const interval = setInterval(tick, 30000);
    return () => clearInterval(interval);
  }, [refreshUser, navigate]);

  function handleLogout() {
    logout();
    navigate('/login', { replace: true });
  }

  async function handleRefresh() {
    const updated = await refreshUser();
    if (updated && updated.status === 'ACTIVE') {
      navigate('/', { replace: true });
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-amber-50 via-gray-50 to-orange-50 p-4">
      <div className="w-full max-w-lg">
        <div className="text-center mb-8">
          <div className="mx-auto w-14 h-14 bg-amber-100 rounded-2xl flex items-center justify-center mb-4">
            <Clock className="w-7 h-7 text-amber-600" />
          </div>
          <h1 className="text-2xl font-bold text-gray-900">Awaiting Approval</h1>
          <p className="text-gray-500 mt-1">Your account is being reviewed by an administrator</p>
        </div>

        <div className="bg-white rounded-2xl border border-gray-200 shadow-xl shadow-gray-200/40 p-8 space-y-5">
          {user && (
            <>
              <div className="flex items-center gap-3 pb-4 border-b border-gray-100">
                <div className="w-10 h-10 bg-primary-50 rounded-lg flex items-center justify-center shrink-0">
                  <Sparkles className="w-5 h-5 text-primary-500" />
                </div>
                <div className="min-w-0">
                  <p className="font-semibold text-gray-900 truncate">{user.business_name}</p>
                  <p className="text-xs text-gray-500 truncate">{user.email}</p>
                </div>
              </div>

              <div className="bg-amber-50 border border-amber-200 rounded-xl p-4">
                <div className="flex items-start gap-3">
                  <Clock className="w-5 h-5 text-amber-500 mt-0.5 shrink-0" />
                  <div>
                    <p className="text-sm font-medium text-amber-800">
                      Status: PENDING
                    </p>
                    <p className="text-sm text-amber-700 mt-1">
                      An admin will review your registration shortly. Once approved, you'll
                      have full access to the dashboard.
                    </p>
                  </div>
                </div>
              </div>

              <div className="bg-blue-50 border border-blue-200 rounded-xl p-4">
                <div className="flex items-start gap-3">
                  <Mail className="w-5 h-5 text-blue-500 mt-0.5 shrink-0" />
                  <div>
                    <p className="text-sm font-medium text-blue-800">
                      What happens next?
                    </p>
                    <ul className="text-sm text-blue-700 mt-1 space-y-1 list-disc list-inside">
                      <li>An admin reviews your application</li>
                      <li>You'll be notified at <strong>{user.email}</strong> when approved</li>
                      <li>This page will auto-refresh every 30 seconds</li>
                    </ul>
                  </div>
                </div>
              </div>
            </>
          )}

          <div className="flex items-center gap-3 pt-2">
            <button
              onClick={handleRefresh}
              className="flex-1 inline-flex items-center justify-center gap-2 px-4 py-2.5 border border-gray-200 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50 transition-colors"
            >
              <RefreshCw className="w-4 h-4" />
              Check status
            </button>
            <button
              onClick={handleLogout}
              className="flex-1 inline-flex items-center justify-center gap-2 px-4 py-2.5 border border-gray-200 text-gray-600 rounded-lg text-sm font-medium hover:bg-gray-50 transition-colors"
            >
              <LogOut className="w-4 h-4" />
              Sign out
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
