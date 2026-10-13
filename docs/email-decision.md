# Email delivery decision

Decision date: 2026-10-13
Status: selected for the first release; the project owner can use a subdomain of an existing domain, but Resend and DNS have not been configured yet

Use Resend for transactional emails about missing-title reports. Clerk handles sign-in messages; the catalog does not need to send its own authentication email.

## Required behavior

- Store a reporter's optional email privately in the application database, linked to the report. Never copy it into a public GitHub issue, PR, or workflow log.
- A missing-title report can create a GitHub issue and notify the admin without an email address. Reporting must remain quick and optional for the user.
- Send a reporter email only after the title is available in the public catalog. A merged PR, manual correction, or provider reconciliation may trigger a check, but none alone proves public availability.
- Use one notification record per report and publication event in the application database. Retry failures, with a Resend idempotency key as short-term duplicate protection; Resend keeps those keys for 24 hours, so the database record is the lasting guard.
- A GitHub Action will trigger reconciliation when a title-fixing PR merges. The application checks public availability and sends the email through Resend; the Action does not need reporter addresses or the Resend API key.
- Keep `RESEND_API_KEY` and the sender address in server-side environment variables. A self-hoster supplies their own Resend account, verified domain, and API key.

## Free-tier boundary

Resend currently offers 3,000 transactional emails per month and 100 per day on its free plan. The project owner already has a domain and can verify a subdomain for this project's sender address, so a new domain purchase is not needed. Production sending still requires adding Resend's DNS records and completing verification. Recheck the limits and domain rules before launch.

## References checked on 2026-10-13

- [Resend pricing](https://resend.com/pricing)
- [Resend verified domains](https://resend.com/docs/dashboard/domains/introduction)
- [Resend Python SDK](https://resend.com/docs/send-with-python)
- [Resend idempotency keys](https://resend.com/docs/dashboard/emails/idempotency-keys)
