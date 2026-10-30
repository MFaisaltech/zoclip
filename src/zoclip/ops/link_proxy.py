"""Loopback-only bridges to two fixed, permission-protected host Unix sockets.

Runs in the AI worker's network namespace, without database secrets or media.
The host socket units forward only to the existing loopback WARP/token services.
"""

import asyncio
from contextlib import suppress

ENDPOINTS = ((40000, "/run/zoclip-link/warp.sock"), (4416, "/run/zoclip-link/pot.sock"))
MAX_CONNECTIONS = 32


async def forward(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    while data := await asyncio.wait_for(reader.read(65536), timeout=120):
        writer.write(data)
        await asyncio.wait_for(writer.drain(), timeout=30)
    if writer.can_write_eof():
        writer.write_eof()


async def bridge(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    path: str,
) -> None:
    upstream = None
    try:
        # Unix streams exist in the Linux deployment; Windows asyncio's type
        # definitions omit this API.
        connect = asyncio.open_unix_connection  # type: ignore[attr-defined]
        remote, upstream = await asyncio.wait_for(connect(path), timeout=5)
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(forward(reader, upstream))
            tasks.create_task(forward(remote, writer))
    except (OSError, TimeoutError, ExceptionGroup):
        # Never log payloads, URLs, token bodies or proxy credentials.
        pass
    finally:
        for stream in (writer, upstream):
            if stream is not None:
                stream.close()
                with suppress(OSError):
                    await stream.wait_closed()


async def serve() -> None:
    active = 0

    async def accept(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, path: str) -> None:
        nonlocal active
        if active >= MAX_CONNECTIONS:
            writer.close()
            return
        active += 1
        try:
            await bridge(reader, writer, path)
        finally:
            active -= 1

    servers = []
    for port, path in ENDPOINTS:

        async def handler(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter, target: str = path
        ) -> None:
            await accept(reader, writer, target)

        servers.append(await asyncio.start_server(handler, "127.0.0.1", port, limit=65536))
    await asyncio.gather(*(server.serve_forever() for server in servers))


if __name__ == "__main__":
    asyncio.run(serve())
