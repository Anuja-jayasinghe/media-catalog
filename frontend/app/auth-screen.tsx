import { SignIn, SignUp } from "@clerk/nextjs";
import { authHref } from "./auth-return";

export function AuthScreen({ mode, returnTo }: { mode: "sign-in" | "sign-up"; returnTo: string }) {
  const signIn = mode === "sign-in";
  const linkedTitle = new URLSearchParams(returnTo.split("?")[1] || "").has("title");
  return <main className="auth-page">
    <a className="auth-brand" href="/" aria-label="MTGL home">MTGL<span>.</span></a>
    <div className="auth-stage">
      <div className="auth-intro">
        <p className="eyebrow">YOUR STORIES, ALL TOGETHER</p>
        <h1>{signIn ? "Welcome back." : "Start your collection."}</h1>
        <p>{linkedTitle ? "Your selected title will be waiting when you return." : "Keep the movies, series, and games that stay with you in one place."}</p>
      </div>
      <div className="auth-card">
        {signIn ? <SignIn routing="path" path="/sign-in" signUpUrl={authHref("sign-up", returnTo)} forceRedirectUrl={returnTo} signUpForceRedirectUrl={returnTo}/> : <SignUp routing="path" path="/sign-up" signInUrl={authHref("sign-in", returnTo)} forceRedirectUrl={returnTo} signInForceRedirectUrl={returnTo}/>}
        <a className="auth-explore" href={returnTo}>{linkedTitle ? "Back to the title" : "Continue exploring"} <span aria-hidden="true">→</span></a>
      </div>
    </div>
  </main>;
}
