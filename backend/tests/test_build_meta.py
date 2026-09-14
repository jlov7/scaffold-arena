from build_meta import build_metadata


def test_build_metadata_uses_safe_standard_deployment_values() -> None:
    metadata = build_metadata({
        "VITE_GIT_SHA": "a" * 40,
        "VERCEL_GIT_COMMIT_SHA": "b" * 40,
        "VERCEL_ENV": "production",
        "BUILD_TIME": "2026-08-18T18:00:00Z",
        "API_SECRET_KEY": "must-not-appear",
    })
    assert metadata == {
        "schema_version": "build-meta.v1",
        "app_version": "0.9.1",
        "protocol_version": "1.0",
        "git_sha": "a" * 40,
        "build_environment": "production",
        "build_time": "2026-08-18T18:00:00Z",
    }


def test_build_metadata_is_truthful_when_deployment_values_are_unset() -> None:
    assert build_metadata({})["git_sha"] == "dev"
    assert build_metadata({})["build_environment"] == "development"
    assert build_metadata({})["build_time"] == "unknown"


def test_build_metadata_uses_railway_values_and_ignores_invalid_shas() -> None:
    metadata = build_metadata({
        "VITE_GIT_SHA": "short",
        "RAILWAY_GIT_COMMIT_SHA": "b" * 40,
        "RAILWAY_ENVIRONMENT_NAME": "staging",
        "SOURCE_DATE_EPOCH": "1787076000",
    })
    assert metadata["git_sha"] == "b" * 40
    assert metadata["build_environment"] == "staging"
    assert metadata["build_time"] == "2026-08-18T18:00:00.000Z"
