# Contributing to MTGL

Thanks for helping improve MTGL. The live app is at [mtgl.anujajay.com](https://mtgl.anujajay.com); this repository contains the source, service setup notes, and the planned product scope.

## Before opening a pull request

1. Check [open issues](https://github.com/Anuja-jayasinghe/media-catalog/issues) and [product requirements](docs/product-requirements.md) so work fits the current scope.
2. For a substantial feature or behavior change, open an issue first to agree on the approach.
3. Keep changes focused, explain user-visible behavior, and update relevant documentation.
4. Never commit `.env` files, API credentials, OAuth secrets, user data, or production database URLs. Use fixtures with synthetic data.

## Local development

Follow the setup in the [README](README.md). The application has a Python API in `backend/` and a Next.js web client in `frontend/`.

Before submitting, run:

```sh
cd backend
uv run pytest
```

```sh
cd frontend
npm run typecheck
npm run build
```

The CI workflow runs these checks and the source-tool unit tests on each pull request.

## Pull request guidance

- Describe the problem and the change, including any setup or migration steps.
- Include test results and screenshots for interface changes when useful.
- Call out changes to provider usage, privacy, data retention, exports, or authentication.
- Keep secrets and personal information out of examples, logs, screenshots, and commit history.

## Reporting security issues

Do not include credentials, personal data, or exploitable details in a public issue. Contact the repository maintainer privately through GitHub if you believe you found a security vulnerability.
