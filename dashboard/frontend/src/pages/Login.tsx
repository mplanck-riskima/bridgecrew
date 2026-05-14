import { GoogleLogin } from "@react-oauth/google";
import { useState } from "react";
import { useNavigate } from "react-router";
import { useAuth } from "@/context/AuthContext";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  async function handleCredential(credentialResponse: { credential?: string }) {
    if (!credentialResponse.credential) {
      setError("No credential returned from Google.");
      return;
    }
    setError(null);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id_token: credentialResponse.credential }),
      });
      if (res.status === 403) {
        setError("This Google account is not authorized.");
        return;
      }
      if (!res.ok) {
        setError("Sign-in failed. Please try again.");
        return;
      }
      const { access_token } = await res.json();
      login(access_token);
      navigate("/", { replace: true });
    } catch {
      setError("Network error. Please try again.");
    }
  }

  return (
    <div className="h-screen bg-lcars-bg flex items-center justify-center">
      <div className="flex flex-col items-center gap-6">
        <div className="text-lcars-orange font-mono text-xs tracking-[0.4em] uppercase mb-2">
          BridgeCrew Access Control
        </div>
        <div className="w-48 h-1 bg-lcars-orange" />
        <GoogleLogin
          onSuccess={handleCredential}
          onError={() => setError("Google sign-in failed. Please try again.")}
        />
        {error && (
          <p className="text-red-400 font-mono text-xs tracking-wider">{error}</p>
        )}
      </div>
    </div>
  );
}
