"""Harbor agent adapter: runs openrouter-agent-cli inside a Harbor task
environment, in one of two configurations.

- mode=unassisted (default): plain headless agent, no acceptance gate.
- mode=policy: acceptance-gate policy — the task's user-owned acceptance
  command must pass before "done" is accepted, with one repair response.

Agent kwargs (``--ak``):
- ``mode=<unassisted|policy>``
- ``verify=<command>`` the acceptance command for policy mode
- ``max_turns=<int>`` optional model/tool iteration budget per task
- ``tool_profile=<full7|core4>`` optional tool surface (default: full7)
- ``system_prompt=<text>`` optional neutral prompt for controlled comparisons
- ``run_id=<text>`` optional request-capture identifier (defaults to Harbor trial ID)
- ``request_timeout=<seconds>`` optional provider request timeout
- ``provider_retries=<int>`` optional retry count after provider errors
- ``repeat_tool_call_limit=<int>`` optional repeated-tool threshold

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
        CliFlag("tool_profile", "ora-tool-profile", choices=["full7", "core4"], default="full7"),
        CliFlag("system_prompt", "ora-system-prompt"),
        CliFlag("run_id", "ora-run-id"),
        CliFlag("request_timeout", "ora-request-timeout"),
        CliFlag("provider_retries", "ora-provider-retries"),
        CliFlag("repeat_tool_call_limit", "ora-repeat-tool-call-limit"),
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
        # Install from a host-mounted checkout when running a local experiment;
        # otherwise use git@main as before. This keeps Harbor runs able to test
        # an unpushed working tree without changing the normal install path.
        install_command = (
            "if [ -n \"${OPENROUTER_AGENT_LOCAL_SOURCE:-}\" ] && "
            "{ [ -f \"$OPENROUTER_AGENT_LOCAL_SOURCE\" ] || "
            "[ -f \"$OPENROUTER_AGENT_LOCAL_SOURCE/pyproject.toml\" ]; }; then "
            "pip install --quiet \"$OPENROUTER_AGENT_LOCAL_SOURCE\"; "
            "else pip install --quiet "
            "git+https://github.com/protostatis/openrouter-agent-cli@main; fi "
            "2>&1"
        )
        await self.exec_as_agent(
            environment,
            command=install_command,
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
        tool_profile = self._flag_kwargs.get("tool_profile", "full7")
        system_prompt = self._flag_kwargs.get("system_prompt")
        run_id = self._flag_kwargs.get("run_id") or str(
            getattr(self, "context_id", None) or getattr(self, "session_id", None) or ""
        )
        request_timeout = self._flag_kwargs.get("request_timeout")
        provider_retries = self._flag_kwargs.get("provider_retries")
        repeat_tool_call_limit = self._flag_kwargs.get("repeat_tool_call_limit")

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
        if str(tool_profile).strip():
            common += f"--tool-profile {shlex.quote(str(tool_profile))} "
        if str(system_prompt).strip():
            common += f"--system-prompt {shlex.quote(str(system_prompt))} "
        if str(run_id).strip():
            common += f"--run-id {shlex.quote(str(run_id))} "
        if request_timeout is not None and str(request_timeout).strip():
            common += f"--request-timeout {shlex.quote(str(request_timeout))} "
        if provider_retries is not None and str(provider_retries).strip():
            common += f"--provider-retries {shlex.quote(str(provider_retries))} "
        if repeat_tool_call_limit is not None and str(repeat_tool_call_limit).strip():
            common += f"--repeat-tool-call-limit {shlex.quote(str(repeat_tool_call_limit))} "
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
