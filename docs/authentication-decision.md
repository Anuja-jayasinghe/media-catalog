# Authentication decision

Status: first-release requirement, confirmed during the requirements interview on 2026-10-13.

## First release

- Use Clerk for user authentication in both the hosted product and self-hosted installations.
- Offer Google and GitHub sign-in, plus email-and-password and one-time email-code sign-in through Clerk.
- The hosted deployment uses the project's Clerk application. A self-hoster configures their own Clerk application and supplies its publishable and secret keys through environment variables. The secret key must remain server-side.
- End users sign in to the catalog; they do not need to create their own Clerk developer accounts.
- A self-hosted installation therefore depends on Clerk's service for authentication in the first release. Offline or Clerk-free authentication is outside this release's scope.

## Future improvement

- Track pluggable authentication as a future feature so a deployment can use an alternative identity provider without replacing the media catalog.
- Keep catalog ownership tied to an application-level user identifier rather than treating a Clerk identifier as the permanent catalog key. This is a design recommendation to make a future auth migration practical; the data model remains to be specified.

## Setup references

- [Clerk application setup](https://clerk.com/docs/getting-started/quickstart/setup-clerk)
- [Sign-in options](https://clerk.com/docs/guides/configure/auth-strategies/sign-up-sign-in-options)
- [Google social sign-in](https://clerk.com/docs/guides/configure/auth-strategies/social-connections/google)
- [Production deployment and keys](https://clerk.com/docs/guides/development/deployment/production)
