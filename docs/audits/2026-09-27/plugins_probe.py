"""Audit 11 characterization; temporary files, mock transports, no external I/O.

Run: PYTHONPATH=src .venv/bin/python docs/audits/2026-09-27/plugins_probe.py
These are observations of the audit baseline, not passing-behavior assertions.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from deepseek_tui.integrations import plugins, skills
from deepseek_tui.integrations.lsp import Language, LspClient, LspConfig, LspManager
from deepseek_tui.plugins.adapters import inspect_local_source
from deepseek_tui.plugins.grants import grant_execution, read_grant, revoke_grant
from deepseek_tui.mcp.config import McpServerConfig
from deepseek_tui.mcp.manager import McpManager
from deepseek_tui.plugins.runtime import CompositeMcpManager
from deepseek_tui.plugins.source import LocalArtifact
from deepseek_tui.plugins.store import publish_source_tree


def plugin(root: Path, name: str = "fixture", scope: str = "user"):
    root.mkdir(parents=True, exist_ok=True)
    return plugins.LoadedPlugin(
        manifest=plugins.PluginManifest(
            name=name,
            hooks=({"event": "session_start", "command": "fixture-not-executed"},),
            mcp_servers={"servers": {"fixture": {"command": "fixture-not-executed"}}},
        ),
        path=root,
        scope=scope,
        enabled=True,
        trusted=True,
    )


async def main():
    results = {}
    with TemporaryDirectory(prefix="audit11-") as tmp:
        root = Path(tmp)
        with patch.dict(os.environ, {"DEEPSEEK_HOME": str(root / "home")}):
            one, two = root / "one", root / "two"
            one.mkdir()
            two.mkdir()
            (one / "a").write_text("bc")
            (two / "ab").write_text("c")
            results["P01_digest_framing"] = {
                "different_trees_same_digest": LocalArtifact(one).digest
                == LocalArtifact(two).digest,
            }
            digest, stored = publish_source_tree(one)
            (stored / "a").write_text("modified")
            reused_digest, reused = publish_source_tree(one)
            results["P02_store_reuse"] = {
                "reused_corrupted_entry": reused == stored,
                "actual_digest_matches_returned": LocalArtifact(reused).digest == reused_digest,
            }
            loaded = plugin(root / "plugin")
            current = plugins._execution_digest_for_plugin(loaded)
            grant_execution("fixture", current, capabilities=frozenset({"hooks.execute"}))
            contrib = plugins.collect_light_contributions([loaded])
            results["P03_capability_separation"] = {
                "granted": ["hooks.execute"],
                "hooks": len(contrib.hook_entries),
                "mcp_servers": len(contrib.mcp_servers),
            }
            revoke_grant("fixture")
            plugins.collect_light_contributions([loaded])
            results["P04_revoke"] = {"grant_recreated": read_grant("fixture", current) is not None}

            forged = root / "arbitrary" / "sources" / "sha256" / current.removeprefix("sha256:")
            forged.mkdir(parents=True)
            (forged / "changed").write_text("different content")
            link = root / "linked"
            link.symlink_to(forged, target_is_directory=True)
            linked = plugin(link, scope="project")
            forged_contrib = plugins.collect_light_contributions([linked])
            results["P02_symlink_identity"] = {
                "project_trust_from_claimed_provenance": plugins._project_trust_from_grants(
                    "fixture", link, {"derived_provenance": {"source": {"digest": current}}}
                ),
                "actual_digest_matches_grant": LocalArtifact(link).digest == current,
                "runtime_digest_matches_grant": plugins._execution_digest_for_plugin(linked)
                == current,
                "collected_hooks": len(forged_contrib.hook_entries),
            }

            source = root / "source"
            source.mkdir()
            (source / "SKILL.md").write_text("original")
            target = root / "skills"
            skills.install(skills.InstallSource.parse(str(source)), target, "demo")
            assert (target / "demo" / "SKILL.md").is_file()
            local_outcome, local_message = skills.update("demo", target)
            results["P05_local_skill_update"] = {
                "outcome": local_outcome.value,
                "message": local_message.split(":")[0],
            }
            (target / "demo" / skills.INSTALLED_FROM_MARKER).write_text(
                json.dumps({"spec": "github:fixture/fixture"})
            )
            with patch.object(
                skills,
                "fetch_github_archive",
                side_effect=skills.GithubFetchError("offline fixture failure"),
            ):
                outcome, _ = skills.update("demo", target)
            results["P05_failed_skill_update"] = {
                "outcome": outcome.value,
                "old_install_exists": (target / "demo").exists(),
            }
            (source / "SKILL.md").write_text("fixture")
            outcome, _ = skills.install(
                skills.InstallSource.parse(str(source)), target, "../outside"
            )
            results["P06_skill_name_escape"] = {
                "outcome": outcome.value,
                "outside_created": (root / "outside" / "SKILL.md").exists(),
            }

            transport = SimpleNamespace(send=AsyncMock())
            client = LspClient(transport, Language.PYTHON)
            pending = asyncio.create_task(client._request("fixture", {}))
            await asyncio.sleep(0)
            pending.cancel()
            try:
                await pending
            except asyncio.CancelledError:
                pass
            results["P07_lsp_cancel"] = {"pending_after_cancel": len(client._pending)}
            path = root / "has space.py"
            client._handle_diagnostics(
                {"uri": path.as_uri(), "diagnostics": [{"message": "fixture"}]}
            )
            results["P08_lsp_uri"] = {
                "published": 1,
                "retrievable": len(client.get_diagnostics(path)),
            }
            client._versions[path.as_posix()] = 3
            client._handle_diagnostics(
                {
                    "uri": f"file://{path.as_posix()}",
                    "version": 1,
                    "diagnostics": [{"message": "old"}],
                }
            )
            results["P08_lsp_version"] = {
                "obsolete_version_accepted": client.get_diagnostics(path)[0].message == "old"
            }

            gate = asyncio.Event()
            instances = []

            class FakeClient:
                def __init__(self, *args):
                    instances.append(self)

                async def start(self):
                    await gate.wait()

                async def close(self):
                    pass

            mgr = LspManager(LspConfig())
            with patch("deepseek_tui.integrations.lsp.LspClient", FakeClient):
                tasks = [
                    asyncio.create_task(mgr._get_or_spawn_client(Language.PYTHON)) for _ in range(2)
                ]
                for _ in range(3):
                    await asyncio.sleep(0)
                gate.set()
                await asyncio.gather(*tasks)
            results["P07_lsp_parallel_start"] = {
                "clients_created": len(instances),
                "clients_owned": len(mgr._clients),
            }
            await mgr.close_all()

            nested = root / "nested-plugin"
            (nested / ".claude-plugin").mkdir(parents=True)
            (nested / ".claude-plugin" / "plugin.json").write_text(
                json.dumps({"name": "nested", "commands": ["commands"]})
            )
            (nested / "commands" / "group").mkdir(parents=True)
            (nested / "commands" / "group" / "hello.md").write_text(
                "---\ndescription: fixture\n---\nhello"
            )
            packages, _ = inspect_local_source(nested)
            loaded_nested = plugins.LoadedPlugin(
                manifest=plugins.load_plugin_manifest(nested),
                path=nested,
                scope="user",
                enabled=True,
                trusted=False,
            )
            results["P11_adapter_runtime_divergence"] = {
                "inspection_commands": sum(
                    c.kind == "prompt.command" for c in packages[0].contributions
                ),
                "runtime_commands": len(
                    plugins.collect_heavy_contributions([loaded_nested]).commands
                ),
            }

            providers = [
                McpManager([McpServerConfig(name="shared", command="unused")]) for _ in range(2)
            ]
            schema = {"type": "function", "function": {"name": "mcp_shared_run"}}
            for index, provider in enumerate(providers):
                provider.discover_tools = AsyncMock(return_value=[schema])
                provider.call_tool = AsyncMock(return_value={"provider": index})
            composite = CompositeMcpManager(*providers)
            catalog = await composite.discover_tools()
            result = await composite.call_tool("mcp_shared_run", {})
            results["P09_composite_collision"] = {
                "same_name_descriptors": len(catalog),
                "selected_provider": result["provider"],
                "second_provider_called": providers[1].call_tool.await_count,
            }
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
