"""Explicit origins that may embed the existing reader without bypassing its auth."""

import ipaddress
import re
from urllib.parse import urlsplit


def parse_allowed_origins(raw: str) -> tuple[str, ...]:
    origins = []
    for value in re.split(r"[,\s]+", raw.strip()):
        if not value:
            continue
        try:
            parsed = urlsplit(value)
            host = parsed.hostname
            port = parsed.port
            if (parsed.scheme not in ("http", "https") or not host or parsed.username is not None
                    or parsed.password is not None or parsed.path not in ("", "/")
                    or parsed.query or parsed.fragment or "%" in host):
                raise ValueError
            try:
                address = ipaddress.ip_address(host)
                host = f"[{address.compressed}]" if address.version == 6 else str(address)
            except ValueError:
                host = host.encode("idna").decode("ascii").lower()
                if not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part)
                           for part in host.split(".")):
                    raise ValueError
            if port is not None and port not in range(1, 65536):
                raise ValueError
            default_port = 80 if parsed.scheme == "http" else 443
            origin = f"{parsed.scheme}://{host}"
            if port is not None and port != default_port:
                origin += f":{port}"
        except (UnicodeError, ValueError) as exc:
            raise ValueError("EMBED_ALLOWED_ORIGINS must contain only exact HTTP(S) origins") from exc
        if origin not in origins:
            origins.append(origin)
    return tuple(origins)


def frame_ancestors(allowed_origins: tuple[str, ...]) -> str:
    return "frame-ancestors 'self'" + "".join(f" {origin}" for origin in allowed_origins)
