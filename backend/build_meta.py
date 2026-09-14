from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import datetime, timezone


APP_VERSION = "0.9.1"
PROTOCOL_VERSION = "1.0"
SHA_ENVIRONMENT_KEYS = (
    "VITE_GIT_SHA",
    "VERCEL_GIT_COMMIT_SHA",
    "RAILWAY_GIT_COMMIT_SHA",
    "GITHUB_SHA",
    "SOURCE_VERSION",
)
ENVIRONMENT_KEYS = (
    "VERCEL_ENV",
    "RAILWAY_ENVIRONMENT_NAME",
    "RAILWAY_ENVIRONMENT",
    "APP_ENV",
)


def build_metadata(environment: Mapping[str, str] | None = None) -> dict[str, str]:
    environment = os.environ if environment is None else environment
    git_sha = next((candidate for key in SHA_ENVIRONMENT_KEYS if (candidate := environment.get(key, "").strip()) and is_full_commit_sha(candidate)), "dev")
    build_environment = next(
        (environment[key].strip() for key in ENVIRONMENT_KEYS if environment.get(key, "").strip()),
        "development",
    )
    return {
        "schema_version": "build-meta.v1",
        "app_version": APP_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "git_sha": git_sha,
        "build_environment": build_environment,
        "build_time": build_time(environment),
    }


def is_full_commit_sha(value: str) -> bool:
    return len(value) in (40, 64) and all(character in "0123456789abcdefABCDEF" for character in value)


def build_time(environment: Mapping[str, str]) -> str:
    source_date_epoch = environment.get("SOURCE_DATE_EPOCH", "").strip()
    if source_date_epoch.isdigit():
        return (
            datetime.fromtimestamp(int(source_date_epoch), tz=timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
    return environment.get("BUILD_TIME", "").strip() or "unknown"
