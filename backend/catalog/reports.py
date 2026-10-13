"""External operations for missing-title reports.

Public issue bodies contain only title details. Reporter addresses stay in the DB.
"""

from __future__ import annotations

import os
import re

import httpx

from .database import MissingTitleReport, ReportSubscriber, Title


def github_settings() -> tuple[str, str] | None:
    token = os.getenv("GITHUB_TOKEN")
    repository = os.getenv("GITHUB_REPOSITORY")
    if not token or not repository or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        return None
    return token, repository


def email_settings() -> tuple[str, str] | None:
    key = os.getenv("RESEND_API_KEY")
    sender = os.getenv("REPORT_FROM_EMAIL")
    if not key or not sender:
        return None
    return key, sender


async def create_github_issue(report: MissingTitleReport) -> tuple[int, str] | None:
    settings = github_settings()
    if settings is None:
        return None
    token, repository = settings
    marker = f"<!-- catalog-report:{report.id} -->"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    async with httpx.AsyncClient(timeout=12.0) as client:
        # A prior request may have succeeded just before the DB write failed.
        existing = await client.get(
            f"https://api.github.com/repos/{repository}/issues",
            params={"state": "all", "per_page": 100}, headers=headers,
        )
        existing.raise_for_status()
        for issue in existing.json():
            if marker in (issue.get("body") or ""):
                return int(issue["number"]), issue["html_url"]
        body = (
            f"A catalog visitor could not find this {report.media_type} title.\n\n"
            f"**Title:** {report.name}\n"
            f"**Media type:** {report.media_type}\n\n"
            "Check the primary and supplemental sources, then add a verified public catalog record. "
            "No reporter contact information is included in this issue.\n\n"
            f"{marker}"
        )
        response = await client.post(
            f"https://api.github.com/repos/{repository}/issues",
            headers=headers, json={"title": f"Missing {report.media_type} title: {report.name}",
                                   "body": body},
        )
        response.raise_for_status()
        issue = response.json()
        return int(issue["number"]), issue["html_url"]


async def close_github_issue(report: MissingTitleReport) -> None:
    settings = github_settings()
    if settings is None or not report.github_issue_number:
        return
    token, repository = settings
    async with httpx.AsyncClient(timeout=12.0) as client:
        response = await client.patch(
            f"https://api.github.com/repos/{repository}/issues/{report.github_issue_number}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28"},
            json={"state": "closed", "state_reason": "completed"},
        )
        response.raise_for_status()


async def send_publication_email(report: MissingTitleReport, subscriber: ReportSubscriber, title: Title) -> str | None:
    settings = email_settings()
    if settings is None:
        return None
    key, sender = settings
    # The title ID is a public catalog URL path, not a provider-only result.
    frontend = os.getenv("PUBLIC_CATALOG_URL", "http://localhost:3000").rstrip("/")
    url = f"{frontend}/?view={title.media_type}&title={title.id}"
    async with httpx.AsyncClient(timeout=12.0) as client:
        response = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                     "Idempotency-Key": f"catalog-published-{report.id}-{subscriber.id}-{title.id}"},
            json={"from": sender, "to": [subscriber.email],
                  "subject": f"{title.name} is now in Media Catalog",
                  "text": f"The title you reported is now available in the public catalog: {url}"},
        )
        response.raise_for_status()
        return response.json().get("id")


async def send_admin_email(report: MissingTitleReport) -> bool:
    settings = email_settings()
    admin = os.getenv("ADMIN_EMAIL")
    if settings is None or not admin:
        return False
    key, sender = settings
    async with httpx.AsyncClient(timeout=12.0) as client:
        response = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                     "Idempotency-Key": f"catalog-admin-report-{report.id}"},
            json={"from": sender, "to": [admin],
                  "subject": f"Missing {report.media_type} title: {report.name}",
                  "text": f"A missing-title report needs review.\nTitle: {report.name}\nType: {report.media_type}\nIssue: {report.github_issue_url or 'Pending'}"},
        )
        response.raise_for_status()
        return True
