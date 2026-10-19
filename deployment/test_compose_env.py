"""Test Compose environment precedence without starting containers or reading local secrets."""

import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import tempfile
import unittest


DEPLOYMENT = Path(__file__).resolve().parent
COMPOSE_FILES = ("compose.yaml", "compose.local.yaml")
PREFIXED_KEY = "DRAWING2CAD_AGENT_LOCAL_API_KEY"


class ComposeEnvironmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docker = shutil.which("docker")
        if cls.docker is None:
            raise unittest.SkipTest("Docker CLI is unavailable.")
        version = subprocess.run(
            [cls.docker, "compose", "version"], capture_output=True, text=True, timeout=30
        )
        if version.returncode:
            raise unittest.SkipTest("Docker Compose is unavailable.")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.deployment = self.root / "deployment"
        self.deployment.mkdir()
        for name in COMPOSE_FILES:
            shutil.copyfile(DEPLOYMENT / name, self.deployment / name)
        # Remove inherited deployment variables. All test values are synthetic.
        self.environment = {
            key: value for key, value in os.environ.items()
            if not key.startswith(("DRAWING2CAD_", "COMPOSE_"))
        }

    def write_env(self):
        (self.root / ".env").write_text(
            "DRAWING2CAD_AGENT_API_KEY=file-key\n"
            "DRAWING2CAD_HTTP_TOKEN=file-token\n"
            "DRAWING2CAD_VERSION=fixture-version\n"
            f"{PREFIXED_KEY}=profile-key\n",
            encoding="utf-8",
        )

    def config(self, name, *, use_env_file=True, shell=None):
        command = [self.docker, "compose"]
        if use_env_file:
            command.extend(("--env-file", str(self.root / ".env")))
        command.extend((
            "-f", str(self.deployment / name), "--profile", "*",
            "config", "--format", "json",
        ))
        # The calling directory must not provide an implicit .env.
        result = subprocess.run(
            command, cwd=self.deployment, env={**self.environment, **(shell or {})},
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)["services"]

    def assert_values(self, services, name, key, token, version):
        self.assertEqual(services["backend"]["environment"]["DRAWING2CAD_AGENT_API_KEY"], key)
        self.assertEqual(services["mcp-http"]["environment"]["DRAWING2CAD_HTTP_TOKEN"], token)
        if name == "compose.yaml":
            for service, image in (
                ("backend", "backend"), ("frontend", "frontend"), ("mcp", "mcp"), ("mcp-http", "mcp")
            ):
                self.assertEqual(
                    services[service]["image"], f"ghcr.io/hackhog/drawing2cad-{image}:{version}"
                )
        else:
            self.assertEqual(services["backend"]["image"], "drawing2cad-backend:local")

    def test_documented_start_commands_load_the_root_file(self):
        self.write_env()
        for name in COMPOSE_FILES:
            with self.subTest(compose=name):
                header = (DEPLOYMENT / name).read_text(encoding="utf-8")
                line = next(line for line in header.splitlines() if line.startswith("#   Web app:"))
                arguments = shlex.split(line.split("docker compose ", 1)[1])
                arguments = arguments[:arguments.index("up")]
                result = subprocess.run(
                    [self.docker, "compose", *arguments, "--profile", "*", "config", "--format", "json"],
                    cwd=self.root, env=self.environment, capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assert_values(
                    json.loads(result.stdout)["services"], name, "file-key", "file-token", "fixture-version"
                )

    def test_root_file_values_reach_both_compose_models(self):
        self.write_env()
        for name in COMPOSE_FILES:
            with self.subTest(compose=name):
                services = self.config(name)
                self.assert_values(services, name, "file-key", "file-token", "fixture-version")
                self.assertEqual(services["backend"]["environment"][PREFIXED_KEY], "profile-key")

    def test_shell_values_override_the_root_file(self):
        self.write_env()
        shell = {
            "DRAWING2CAD_AGENT_API_KEY": "shell-key",
            "DRAWING2CAD_HTTP_TOKEN": "shell-token",
            "DRAWING2CAD_VERSION": "shell-version",
        }
        for name in COMPOSE_FILES:
            with self.subTest(compose=name):
                services = self.config(name, shell=shell)
                self.assert_values(services, name, "shell-key", "shell-token", "shell-version")
                self.assertEqual(services["backend"]["environment"][PREFIXED_KEY], "profile-key")

    def test_optional_file_can_be_absent(self):
        for name in COMPOSE_FILES:
            with self.subTest(compose=name):
                services = self.config(name, use_env_file=False)
                self.assert_values(services, name, "", "", "latest")

    def test_shell_only_configuration_needs_no_file(self):
        for name in COMPOSE_FILES:
            with self.subTest(compose=name):
                services = self.config(name, use_env_file=False, shell={
                    "DRAWING2CAD_AGENT_API_KEY": "shell-key",
                    "DRAWING2CAD_HTTP_TOKEN": "shell-token",
                    "DRAWING2CAD_VERSION": "shell-version",
                })
                self.assert_values(services, name, "shell-key", "shell-token", "shell-version")

    def test_explicitly_empty_shell_values_have_priority(self):
        self.write_env()
        for name in COMPOSE_FILES:
            with self.subTest(compose=name):
                services = self.config(name, shell={"DRAWING2CAD_AGENT_API_KEY": ""})
                self.assert_values(services, name, "", "file-token", "fixture-version")


if __name__ == "__main__":
    unittest.main()
