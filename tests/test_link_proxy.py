"""Real byte forwarding; no WARP, YouTube, credentials or paid API needed."""

import asyncio
import os
from functools import partial

import pytest

from zoclip.ops.link_proxy import bridge


@pytest.mark.skipif(os.name == "nt", reason="Unix sockets require the Linux runtime")
def test_unix_bridge_roundtrip_and_missing_socket(tmp_path):
    async def run():
        path = str(tmp_path / "echo.sock")

        async def echo(reader, writer):
            writer.write(await reader.read())
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        unix = await asyncio.start_unix_server(echo, path)
        tcp = await asyncio.start_server(partial(bridge, path=path), "127.0.0.1", 0)
        try:
            port = tcp.sockets[0].getsockname()[1]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"bounded private bytes")
            await writer.drain()
            writer.write_eof()
            assert await asyncio.wait_for(reader.read(), 5) == b"bounded private bytes"
            writer.close()
            await writer.wait_closed()
        finally:
            tcp.close()
            unix.close()
            await tcp.wait_closed()
            await unix.wait_closed()

        tcp = await asyncio.start_server(
            partial(bridge, path=str(tmp_path / "missing.sock")), "127.0.0.1", 0
        )
        try:
            reader, writer = await asyncio.open_connection(
                "127.0.0.1", tcp.sockets[0].getsockname()[1]
            )
            assert await asyncio.wait_for(reader.read(), 5) == b""
            writer.close()
            await writer.wait_closed()
        finally:
            tcp.close()
            await tcp.wait_closed()

    asyncio.run(run())
