"""Harbor agent adapter: runs openrouter-agent-cli inside a Harbor task
environment, in one of two configurations.

- mode=unassisted (default): plain headless agent, no acceptance gate.
- mode=policy: acceptance-gate policy — the task's user-owned acceptance
  command must pass before "done" is accepted, with one repair response.

Agent kwargs (``--ak``):
- ``mode=<unassisted|policy>``
- ``verify=<command>`` the acceptance command for policy mode
- ``max_turns=<int>`` optional model/tool iteration budget per task

Example:
    harbor run --dataset my-local-dataset@1.0 \
        --agent openrouter_agent_cli.harbor_agent:OraAgent \
        --model openrouter/nvidia/nemotron-3-super-120b-a12b:free \
        --ak mode=policy --ak verify="python3 ./verifiers/verify_x.py"
"""
from __future__ import annotations

import os
import shlex
from typing import override

from harbor.agents.installed.base import BaseInstalledAgent, CliFlag
from harbor.agents.model_connection import ModelConnectionSpec
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext


class OraAgent(BaseInstalledAgent):
    """openrouter-agent-cli as a Harbor agent (unassisted or one-repair policy)."""

    MODEL_CONNECTION = ModelConnectionSpec(
        default_provider="openrouter",
        api_key_envs=("OPENROUTER_API_KEY",),
    )
    CLI_FLAGS = [
        CliFlag("mode", "ora-mode", choices=["unassisted", "policy"], default="unassisted"),
        CliFlag("verify", "ora-verify"),
        CliFlag("max_turns", "ora-max-turns"),
    ]

    @staticmethod
    @override
    def name() -> str:
        return "ora"

    @override
    def version(self) -> str:
        return "0.2.1"

    @override
    async def install(self, environment: BaseEnvironment) -> None:
        # Install the CLI from git@main: the adapter + --allow-tools are on
        # main, unreleased on PyPI yet.
        await self.exec_as_agent(
            environment,
            command=(
                "pip install --quiet "
                "git+https://github.com/protostatis/openrouter-agent-cli@main "
                "2>&1 | tail -1"
            ),
            timeout_sec=600,
        )

    @override
    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        access = self.model_connection
        api_key = access.api_key
        if not api_key:
            raise ValueError("no OPENROUTER_API_KEY for the openrouter provider")
        # Harbor passes provider-qualified names (openrouter/<id>); our CLI
        # wants the raw OpenRouter model id.
        raw_model = self.model_name or "nvidia/nemotron-3-super-120b-a12b:free"
        model = raw_model.split("/", 1)[-1] if raw_model.startswith("openrouter/") else raw_model

        mode = self._flag_kwargs.get("mode", "unassisted")
        verify = self._flag_kwargs.get("verify") or ""
        max_turns = self._flag_kwargs.get("max_turns")

        env = {**access.env, "OPENROUTER_API_KEY": api_key}
        # Route the CLI's OpenRouter traffic through the capture proxy when
        # the host sets OPENROUTER_BASE_URL (containers reach the host via
        # host.docker.internal). Harbor's own connection resolution does not
        # always pass this through to the agent env.
        env["OPENROUTER_BASE_URL"] = os.environ.get(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        )
        escaped = shlex.quote(instruction)
        model_q = shlex.quote(model)
        common = (
            f"openrouter-agent --allow-tools "
            f"--model {model_q} --workdir . --prompt {escaped} "
        )
        if max_turns is not None and str(max_turns).strip():
            common += f"--max-turns {shlex.quote(str(max_turns))} "
        if mode == "policy" and verify:
            command = (
                f"{common}--task {escaped} "
                f"--verify-command {shlex.quote(verify)} "
                f"2>&1 | stdbuf -oL tee /logs/agent/ora.txt"
            )
        else:
            command = f"{common}2>&1 | stdbuf -oL tee /logs/agent/ora.txt"
        await self.exec_as_agent(
            environment,
            command=command,
            env=env,
            cwd="/app",
            timeout_sec=1200,
        )
