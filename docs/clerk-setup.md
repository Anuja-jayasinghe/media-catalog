# Connect Clerk

Each self-hosted deployment uses its own Clerk application. The repository contains no shared credentials.

1. Create a Clerk application. Enable the sign-in methods you want to offer, such as email, Google, and GitHub. Use its development instance for local work.
2. Set `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` and `CLERK_SECRET_KEY` in `frontend/.env.local`. Set the same `CLERK_SECRET_KEY` in `backend/.env`.
3. Set `FRONTEND_ORIGINS` and `CLERK_AUTHORIZED_PARTIES` in the backend to the exact frontend origin, such as `http://localhost:3000`. For multiple origins, use comma-separated values. Set `NEXT_PUBLIC_API_BASE_URL` in the frontend when the API is not on `http://localhost:8000`.
4. Start both services, create a development test account, and verify that a signed-in user can add a title, see it in **My library**, and remove it. The same library endpoint should reject a request without a session token. Clerk's development test emails use the `+clerk_test` subaddress and verification code `424242`.

`CLERK_JWT_KEY` is optional. When omitted, the backend uses Clerk's key discovery; when supplied, it must be the public key for that Clerk instance. The backend accepts session tokens only and checks their authorized party against `CLERK_AUTHORIZED_PARTIES`.

For a public deployment, create or switch to a Clerk production instance, configure the live domain and sign-in methods there, and set its production keys and the deployed frontend origin in the hosting environments. Do not use development keys for public sign-in. The frontend can still serve public catalog discovery without Clerk configuration, but saving to personal libraries will be unavailable.
