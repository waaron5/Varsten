import Link from "next/link";

export default function AuthenticationErrorPage() {
  return (
    <main className="auth-error-page">
      <section className="empty auth-error-card" aria-labelledby="auth-error-title">
        <h1 className="et" id="auth-error-title">Sign-in could not be completed</h1>
        <p className="es">
          Your session was not created. This can happen when a sign-in request expires or is cancelled.
        </p>
        <div className="auth-error-actions">
          <a className="btn primary" href="/auth/login">Try signing in again</a>
          <Link className="btn" href="/">Return home</Link>
        </div>
      </section>
    </main>
  );
}
