import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuth, roleHome } from "../lib/auth";

/**
 * Landing route after the /api/auth/google/oauth/callback redirect.
 * Grabs the ?access=<jwt>&refresh=<jwt> tokens from the URL, hydrates auth,
 * then bounces to the correct role home. Renders a small "signing you in…"
 * card while the request is in flight.
 */
export default function OAuthComplete() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { completeOAuthFromTokens } = useAuth();
  const [error, setError] = useState(null);

  useEffect(() => {
    const access = params.get("access");
    const refresh = params.get("refresh");
    if (!access || !refresh) {
      setError("Missing tokens in the OAuth callback URL.");
      return;
    }
    completeOAuthFromTokens(access, refresh)
      .then(({ user }) => navigate(roleHome(user.role), { replace: true }))
      .catch((e) => setError(e?.response?.data?.detail || e.message || "Login failed"));
  }, [params, completeOAuthFromTokens, navigate]);

  return (
    <div
      data-testid="oauth-complete-screen"
      className="min-h-screen flex items-center justify-center bg-slate-950 text-slate-100 p-6"
    >
      <div className="max-w-sm w-full bg-slate-900 border border-slate-800 rounded-2xl p-8 text-center">
        <h1 className="text-lg font-semibold mb-2" data-testid="oauth-complete-title">
          {error ? "Sign-in failed" : "Signing you in…"}
        </h1>
        <p className="text-sm text-slate-400" data-testid="oauth-complete-message">
          {error || "Just a moment while we hand you off to your portal."}
        </p>
        {error && (
          <button
            data-testid="oauth-complete-retry-btn"
            className="mt-6 px-4 py-2 rounded-lg bg-emerald-500 text-slate-950 font-medium"
            onClick={() => navigate("/login", { replace: true })}
          >
            Back to sign-in
          </button>
        )}
      </div>
    </div>
  );
}
