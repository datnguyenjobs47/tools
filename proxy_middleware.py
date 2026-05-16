import asyncio
import base64
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ProxyMiddleware")

class LocalProxyMiddleware:
    def __init__(self, local_port: int, upstream_host: str, upstream_port: int, username: str = None, password: str = None):
        self.local_port = local_port
        self.upstream_host = upstream_host
        self.upstream_port = upstream_port
        self.auth_str = None
        
        if username and password:
            auth_bytes = f"{username}:{password}".encode('ascii')
            self.auth_str = f"Basic {base64.b64encode(auth_bytes).decode('ascii')}"
            logger.info(f"Auth enabled for upstream proxy: {upstream_host}:{upstream_port}")

    async def pipe(self, reader, writer):
        try:
            while not reader.at_eof():
                data = await reader.read(4096)
                if not data:
                    break
                writer.write(data)
                await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    async def handle_client(self, client_reader, client_writer):
        try:
            # 1. Đọc request line đầu tiên từ Chrome
            data = await client_reader.read(4096)
            if not data:
                client_writer.close()
                return

            header_lines = data.split(b'\r\n')
            first_line = header_lines[0].decode('ascii')
            
            # 2. Kết nối tới Upstream Proxy
            upstream_reader, upstream_writer = await asyncio.open_connection(
                self.upstream_host, self.upstream_port
            )

            # 3. Xử lý HTTP CONNECT (Cho HTTPS) hoặc Plain HTTP
            if first_line.startswith('CONNECT'):
                # Gửi CONNECT tới upstream kèm Auth
                connect_req = [f"{first_line}"]
                if self.auth_str:
                    connect_req.append(f"Proxy-Authorization: {self.auth_str}")
                connect_req.append("\r\n")
                
                upstream_writer.write("\r\n".join(connect_req).encode('ascii'))
                await upstream_writer.drain()
                
                # Đọc phản hồi từ Upstream
                resp = await upstream_reader.read(4096)
                client_writer.write(resp)
                await client_writer.drain()
            else:
                # Đối với Plain HTTP, chèn Auth vào header và gửi đi
                new_headers = []
                for line in header_lines:
                    if line.startswith(b"Proxy-Authorization:"):
                        continue
                    if line == b"":
                        if self.auth_str:
                            new_headers.append(f"Proxy-Authorization: {self.auth_str}".encode('ascii'))
                    new_headers.append(line)
                
                upstream_writer.write(b"\r\n".join(new_headers))
                await upstream_writer.drain()

            # 4. Tạo đường ống 2 chiều (Piping)
            await asyncio.gather(
                self.pipe(client_reader, upstream_writer),
                self.pipe(upstream_reader, client_writer)
            )
        except Exception as e:
            logger.error(f"Error handling client: {e}")
            client_writer.close()

    async def start(self):
        server = await asyncio.start_server(self.handle_client, '127.0.0.1', self.local_port)
        logger.info(f"Local Proxy Middleware started on 127.0.0.1:{self.local_port}")
        async with server:
            await server.serve_forever()

if __name__ == "__main__":
    # Cấu hình Upstream Proxy của bạn ở đây
    UPSTREAM_HOST = "your_proxy_host"
    UPSTREAM_PORT = 8080
    USER = "your_user"
    PASS = "your_pass"
    LOCAL_PORT = 8888

    proxy = LocalProxyMiddleware(LOCAL_PORT, UPSTREAM_HOST, UPSTREAM_PORT, USER, PASS)
    try:
        asyncio.run(proxy.start())
    except KeyboardInterrupt:
        pass
