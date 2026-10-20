import asyncio
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import aiohttp

BASES = {
    'https://v2biggerz.live/nitro/integrations/discord/v1': 'v2biggerz.live',
    'https://www.biggerz.com/nitro/integrations/discord/v1': 'www.biggerz.com',
}


def expiry(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


class APIError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(f'BiggerZ HTTP {status}: {code}')


class BiggerZ:
    def __init__(self, base, key):
        self.base = base.rstrip('/')
        if self.base not in BASES:
            raise ValueError('Unsupported BIGGERZ_API_BASE_URL')
        self.key = key
        self.session = None
        self.lock = asyncio.Lock()
        self.next_call = 0.0
        self.cooldown = 0.0

    async def start(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))

    async def close(self):
        if self.session:
            await self.session.close()

    def valid_link(self, url):
        parsed = urlparse(url)
        return (parsed.scheme == 'https' and parsed.netloc == BASES[self.base]
                and parsed.path == '/link/discord' and bool(parsed.query))

    async def request(self, method, path, body=None, params=None, deadline=None):
        # Shared limiter: less than 100 requests/minute across every bot task.
        for attempt in range(4):
            async with self.lock:
                delay = max(self.next_call, self.cooldown) - time.monotonic()
                if deadline and time.time() + max(0, delay) >= deadline:
                    raise APIError(408, 'expired')
                if delay > 0:
                    await asyncio.sleep(delay)
                if deadline and time.time() >= deadline:
                    raise APIError(408, 'expired')
                self.next_call = time.monotonic() + 0.65
                try:
                    async with self.session.request(
                        method, self.base + path, json=body, params=params,
                        headers={'Authorization': 'Bearer ' + self.key},
                        allow_redirects=False,
                    ) as response:
                        status = response.status
                        if status == 204:
                            return None
                        try:
                            data = await response.json(content_type=None)
                        except (ValueError, aiohttp.ContentTypeError):
                            data = {}
                        if 200 <= status < 300:
                            return data
                        code = data.get('error', {}).get('code', 'invalid_response') if isinstance(data, dict) else 'invalid_response'
                        error = APIError(status, code)
                        if status == 429:
                            try:
                                wait = max(1.0, float(response.headers.get('Retry-After', '60')))
                            except ValueError:
                                wait = 60.0
                            self.cooldown = time.monotonic() + wait
                            # Per-user create limits should not trigger repeated link creation.
                            if method == 'POST':
                                raise error
                        elif status < 500:
                            raise error
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    error = APIError(0, 'network_error')
            if attempt == 3:
                raise error
            wait = min(2 ** attempt, 60)
            if deadline and time.time() + wait >= deadline:
                raise APIError(408, 'expired')
            await asyncio.sleep(wait)
