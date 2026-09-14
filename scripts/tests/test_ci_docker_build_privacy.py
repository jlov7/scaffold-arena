from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
BUILDS = {
    "Build backend image": "docker buildx build --file backend/Dockerfile --target prod backend",
    "Build frontend image": "docker buildx build --file frontend/Dockerfile --target prod frontend",
    "Build combined production image": "docker buildx build --file Dockerfile .",
}
BUILDX_ACTION = "docker/setup-buildx-action@bb05f3f5519dd87d3ba754cc423b652a5edd6d2c"


class CIDockerBuildPrivacyTests(unittest.TestCase):
    def test_docker_build_job_uses_direct_buildx_without_push_action_metadata(self) -> None:
        source = WORKFLOW.read_text(encoding="utf-8")
        workflow = yaml.safe_load(source)
        steps = workflow["jobs"]["docker-build"]["steps"]

        self.assertNotIn("docker/build-push-action", source)
        setup = next(step for step in steps if step["name"] == "Setup Docker Buildx")
        self.assertEqual(setup["uses"], BUILDX_ACTION)

        build_steps = {step["name"]: step for step in steps if step["name"] in BUILDS}
        self.assertEqual(set(build_steps), set(BUILDS))
        for name, command in BUILDS.items():
            step = build_steps[name]
            self.assertEqual(step.get("run"), command)
            self.assertNotIn("uses", step)
            self.assertNotIn("with", step)
            self.assertNotIn("--push", command)


if __name__ == "__main__":
    unittest.main()
