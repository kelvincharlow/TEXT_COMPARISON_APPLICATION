import { useEffect, useState } from "react";
import { currentUser, login, logout } from "./api.js";
import logo from "./logo.jpg";
import "./signin.css";

export default function AccountGate({ children }) {
  const [user, setUser] = useState(null);
  const [showPassword, setShowPassword] = useState(false);
  const [checking, setChecking] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    currentUser().then((value) => { if (active) setUser(value); }).catch((err) => {
      if (active && err.status !== 401) setError(err.message);
    }).finally(() => { if (active) setChecking(false); });
    const expired = () => setUser(null);
    window.addEventListener("postbank-session-expired", expired);
    return () => { active = false; window.removeEventListener("postbank-session-expired", expired); };
  }, []);
  async function signIn(event) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    setBusy(true); setError("");
    try { setUser(await login(fields.get("email"), fields.get("password"))); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  async function signOut() {
    setBusy(true); setError("");
    try { await logout(); setUser(null); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  if (checking) return <div className="signin-loading" role="status">Opening your workspace…</div>;
  if (user) return <>
    {!user.roles.some((role) => ["staff", "manager", "administrator"].includes(role)) && <div className="account-bar"><span>{user.full_name} · {user.department}</span><button className="secondary-button" onClick={signOut} disabled={busy}>Sign out</button></div>}
    {error && <p className="error-banner" role="alert">{error}</p>}
    {children(user, { signOut, busy })}
  </>;
  return <div className="signin-backdrop"><main className="signin-shell">
    <section className="signin-entry" aria-labelledby="signin-heading">
      <div className="signin-form-wrap">
        <img className="signin-logo" src={logo} alt="Postbank — My Bank, My Choice, My Future" />
        <h1 id="signin-heading">DOCUMENT WORKSPACE</h1>
        <form onSubmit={signIn} className="signin-form">
          <div className="signin-field"><label htmlFor="signin-email">Work email</label><input id="signin-email" name="email" type="email" autoComplete="username" placeholder="you@your-work-domain.com" required maxLength={254} disabled={busy} /></div>
          <div className="signin-field"><label htmlFor="signin-password">Password</label><div className="signin-password-wrap"><input id="signin-password" name="password" type={showPassword ? "text" : "password"} autoComplete="current-password" placeholder="Enter your password" required maxLength={128} disabled={busy} /><button className="signin-password-toggle" type="button" aria-label={showPassword ? "Hide password" : "Show password"} aria-controls="signin-password" aria-pressed={showPassword} disabled={busy} onClick={() => setShowPassword(!showPassword)}>{showPassword ? "Hide" : "Show"}</button></div></div>
          {error && <p className="signin-error" role="alert">{error}</p>}
          <button className="signin-submit" disabled={busy}><span>{busy ? "Signing in…" : "Sign in"}</span><span aria-hidden="true">{busy ? "…" : "→"}</span></button>
        </form>
        <div className="signin-help"><span className="signin-help-icon" aria-hidden="true">?</span><p>Need access or a password reset?<br /><strong>Contact your administrator.</strong></p></div>
      </div>
      <p className="signin-entry-footer"><svg width="14" height="16" viewBox="0 0 14 16" fill="none" aria-hidden="true"><rect x="2" y="7" width="10" height="8" rx="2" stroke="currentColor" /><path d="M4 7V4a3 3 0 0 1 6 0v3" stroke="currentColor" /></svg> For authorized Postbank staff</p>
    </section>
  </main></div>;
}
