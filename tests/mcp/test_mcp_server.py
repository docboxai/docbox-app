"""The MCP server, through a real MCP client: in-process for the tools, and once over
stdio (`docbox mcp`) as an agent would start it."""

from __future__ import annotations

import os
import sys
import time

import pytest
from mcp.client.client import Client
from mcp.client.stdio import StdioServerParameters

from docbox.mcp_server import server

pytestmark = pytest.mark.anyio


@pytest.fixture()
def anyio_backend():
    return "asyncio"


async def call(client: Client, tool: str, **args):
    result = await client.call_tool(tool, args)
    assert not result.is_error, result.content[0].text
    sc = result.structured_content
    return sc["result"] if isinstance(sc, dict) and set(sc) == {"result"} else sc


async def call_error(client: Client, tool: str, **args) -> str:
    result = await client.call_tool(tool, args)
    assert result.is_error
    return result.content[0].text


async def test_tools_are_listed_with_annotations() -> None:
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert {"get_device", "list_models", "install_model", "read_file", "start_benchmark",
            "get_benchmark", "get_benchmark_page", "remove_model"} <= set(tools)
    assert tools["remove_model"].annotations.destructive_hint is True
    assert tools["list_models"].annotations.read_only_hint is True
    assert tools["get_benchmark"].output_schema is not None


async def test_device_models_and_settings(fake_model, data_dir) -> None:
    async with Client(server) as client:
        device = await call(client, "get_device")
        assert device["data_dir"] == str(data_dir)
        ids = {m["id"] for m in await call(client, "list_models")}
        assert "test-fake" in ids and "paddleocr-mobile-en" in ids
        assert all(m["status"] == "ready"
                   for m in await call(client, "list_models", status="ready"))
        settings = await call(client, "update_settings", default_model_id="test-fake")
        assert settings["default_model_id"] == "test-fake"
        assert "not_found" in await call_error(client, "get_model", model_id="nope")


async def test_install_poll_read_and_remove(fake_model, sample_image, tmp_path) -> None:
    async with Client(server) as client:
        job = await call(client, "install_model", model_id="test-fake")
        deadline = time.monotonic() + 10
        while job["state"] not in ("done", "error"):
            assert time.monotonic() < deadline
            job = await call(client, "get_install_status", job_id=job["job_id"])
        assert job["state"] == "done"

        read = await call(client, "read_file", path=str(sample_image), model_id="test-fake",
                          include_lines=True)
        assert read["text"].startswith("Total due")
        assert read["pages"][0]["lines"][0]["confidence"] == 0.9
        assert read["output_path"].endswith("invoice.txt")

        assert await call(client, "remove_model", model_id="test-fake") == "Removed test-fake"
        assert "not downloaded" in await call_error(
            client, "read_file", path=str(sample_image), model_id="test-fake")


async def test_read_file_needs_a_model(data_dir, sample_image) -> None:
    async with Client(server) as client:
        assert "no model_id" in await call_error(client, "read_file", path=str(sample_image))


async def test_benchmark_start_poll_page_and_report(fakes, docs) -> None:
    async with Client(server) as client:
        run = await call(client, "start_benchmark", paths=[str(docs)],
                         models=["fake-good", "fake-sloppy"], name="Invoices")
        deadline = time.monotonic() + 60
        while run["state"] not in ("done", "error", "cancelled", "interrupted"):
            assert time.monotonic() < deadline
            run = await call(client, "get_benchmark", run_id=run["id"])
        assert run["state"] == "done"
        assert run["summary"]["best_model_id"] == "fake-good"

        page = await call(client, "get_benchmark_page", run_id=run["id"], file_id="invoice.png")
        assert {r["model_id"]: r["slips"] for r in page["reads"]} == {
            "fake-good": 0, "fake-sloppy": 2}

        listed = await call(client, "list_benchmarks")
        assert listed[0]["id"] == run["id"] and listed[0]["best_model_id"] == "fake-good"

        report = await client.read_resource(f"docbox://benchmarks/{run['id']}/report")
        assert report.contents[0].text.startswith("# Invoices")

        assert "conflict" in await call_error(client, "cancel_benchmark", run_id=run["id"])
        assert await call(client, "delete_benchmark", run_id=run["id"]) == f"Deleted {run['id']}"


async def test_bad_benchmark_input_is_a_tool_error(fakes, tmp_path) -> None:
    async with Client(server) as client:
        assert "not_found" in await call_error(
            client, "start_benchmark", paths=[str(tmp_path / "missing")], models=["fake-good"])


async def test_over_stdio_with_a_noisy_engine(installed_fake, sample_image, data_dir, monkeypatch):
    """`docbox mcp` as an agent starts it. The read runs in the server process, and an
    engine that prints to stdout must not corrupt the protocol stream."""
    plugin = data_dir.parent / "noisy_plugin.py"
    plugin.write_text(
        "from docbox.backend.core.registry import ModelSpec, registry\n"
        "from docbox.backend.schemas import OcrLine, OcrResult\n"
        "class E:\n"
        "    def is_downloaded(self): return True\n"
        "    def load(self): print('chatty library output')\n"
        "    def run(self, image):\n"
        "        print('more chatter')\n"
        "        return OcrResult(model_id='noisy', lines=[OcrLine(text='hi')], text='hi')\n"
        "registry.register(ModelSpec(id='noisy', name='Noisy', engine='x', description='',\n"
        "    languages=[], approx_download_mb=0, approx_ram_mb=0, min_disk_mb=0,\n"
        "    engine_factory=E))\n"
    )
    env = {**os.environ, "DOCBOX_DATA_DIR": str(data_dir),
           "PYTHONPATH": os.pathsep.join([str(plugin.parent), os.environ.get("PYTHONPATH", "")]),
           "DOCBOX_PRELOAD": "noisy_plugin"}
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "docbox.cli", "mcp"],
        env=env,
    )
    async with Client(params) as client:
        read = await call(client, "read_file", path=str(sample_image), model_id="noisy")
        assert read["text"] == "hi"
        device = await call(client, "get_device")
        assert device["data_dir"] == str(data_dir)
