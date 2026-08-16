import asyncio

from tests.web.support import AdminWebServer, setup


def test_web_server_start_read_request_and_close(tmp_path):
    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        server = AdminWebServer(database, access, campaigns, sessions, bot)
        reader = asyncio.StreamReader()
        reader.feed_data(b'POST /schedule HTTP/1.1\r\nContent-Length: 3\r\n\r\na=1')
        reader.feed_eof()
        request = await server._read_request(reader)
        await server.start('127.0.0.1', 0)
        assert server._server is not None
        await server.close()
        await server.close()
        await database.close()
        return request

    method, target, headers, body = asyncio.run(scenario())
    assert (method, target, headers['content-length'], body) == ('POST', '/schedule', '3', b'a=1')


def test_web_server_handles_http_response(tmp_path):
    class Writer:
        def __init__(self):
            self.data = b''
            self.closed = False

        def write(self, data):
            self.data += data

        async def drain(self):
            pass

        def close(self):
            self.closed = True

        async def wait_closed(self):
            pass

        def get_extra_info(self, name):
            return ('127.0.0.1', 12345) if name == 'peername' else None

    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        server = AdminWebServer(database, access, campaigns, sessions, bot)
        reader = asyncio.StreamReader()
        reader.feed_data(b'GET / HTTP/1.1\r\nHost: localhost\r\n\r\n')
        reader.feed_eof()
        writer = Writer()
        await server._handle(reader, writer)
        await database.close()
        return writer

    writer = asyncio.run(scenario())
    assert writer.data.startswith(b'HTTP/1.1 200 OK')
    assert b'/login' in writer.data and b'/register' in writer.data
    assert b'Content-Security-Policy' in writer.data
    assert writer.closed


def test_web_trusts_forwarded_headers_only_from_configured_proxy(monkeypatch, caplog):
    monkeypatch.setenv('D20_BOT_WEB_TRUSTED_PROXIES', '10.0.0.0/8, 2001:db8::/32, invalid-network')

    assert AdminWebServer._trusted_proxy('10.2.3.4')
    assert AdminWebServer._trusted_proxy('2001:db8::1')
    assert not AdminWebServer._trusted_proxy('192.0.2.1')
    assert not AdminWebServer._trusted_proxy('not-an-address')
    assert not AdminWebServer._trusted_proxy(None)
    assert 'Invalid trusted proxy network' in caplog.messages
