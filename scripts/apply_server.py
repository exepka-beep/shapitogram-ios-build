#!/usr/bin/env python3
"""Point the ShapitoGram iOS client at our own MTProto server.

The branding patch (``patches/0001-shapitogram-branding-and-server.patch``)
replaces Telegram's production seed-address list with a single entry for our
server, but the concrete host and port differ per deployment. Keeping them in a
script rather than in the patch means a new server needs no code edit: set
``CUSTOM_HOST`` / ``CUSTOM_PORT`` and rebuild.

Why two addresses
-----------------
``seedAddressList`` is a *list* per datacenter, and MtProtoKit genuinely tries
every entry in it (``MTDiscoverConnectionSignals discoverSchemeWithContext:...
addressList:`` builds one probe signal per address and races them), so a second
entry is a real fallback and not decoration. We put the domain first and the
raw IP second: the domain survives an IP change on the hoster's side, while the
IP still works if DNS is broken, hijacked or filtered on the user's network.
Losing the bootstrap address means the app never gets far enough to fetch the
real address list from the server, so this is the one place where a spare is
worth the two extra strings.

Set ``CUSTOM_HOST_ALT`` to the IP to get that pair; leave it empty for a single
entry. Both are validated so a typo cannot produce a Swift syntax error that
only shows up 60 runner-minutes later.

Usage
-----
    CUSTOM_HOST=example.com CUSTOM_HOST_ALT=1.2.3.4 CUSTOM_PORT=2398 \
        apply_server.py <telegram-ios-source-dir>

Idempotent: a second run with the same values changes nothing.
"""

import os
import pathlib
import re
import sys

TARGET = "submodules/TelegramCore/Sources/Network/Network.swift"

# A host or IP as it may appear inside a Swift string literal. Deliberately
# narrow: no quotes, no whitespace, no backslashes, no brackets.
HOST_RE = re.compile(r"^[A-Za-z0-9._:-]+$")


def read_raw(path):
    """Read without newline translation so line endings survive untouched."""
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return handle.read()


def write_raw(path, text):
    """Write with LF only; a stray CRLF would break the patch tooling."""
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def read_host(env_name, required):
    value = os.environ.get(env_name, "").strip()
    if not value:
        if required:
            raise SystemExit(
                "%s не задан. Укажи адрес сервера ShapitoGram в env workflow."
                % env_name
            )
        return ""
    if not HOST_RE.match(value):
        raise SystemExit(
            "%s=%r не похож на хост или IP: допустимы только буквы, цифры, "
            "точка, дефис, двоеточие и подчёркивание." % (env_name, value)
        )
    return value


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)

    host = read_host("CUSTOM_HOST", required=True)
    alt = read_host("CUSTOM_HOST_ALT", required=False)
    port = os.environ.get("CUSTOM_PORT", "").strip()

    if not port.isdigit():
        raise SystemExit("CUSTOM_PORT должен быть числом, получили %r" % port)
    if alt and alt == host:
        # Not an error, just pointless -- and it would look like a mistake in
        # the built binary's address list.
        raise SystemExit("CUSTOM_HOST_ALT совпадает с CUSTOM_HOST (%r)" % alt)

    source_dir = pathlib.Path(sys.argv[1])
    target = source_dir / TARGET
    if not target.is_file():
        raise SystemExit("not found: %s" % target)

    text = read_raw(target)
    original = text

    # 1. Адреса внутри seedAddressList = [ <dc>: [ ... ] ].
    #
    # Меняем всё содержимое внутреннего списка, а не одну строку в кавычках:
    # так скрипт переживает и один адрес, и два, и любое их число в патче.
    addresses = '"%s"' % host
    if alt:
        addresses += ', "%s"' % alt

    pattern_ip = re.compile(r'(seedAddressList\s*=\s*\[\s*\d+:\s*\[)[^\]]*(\])')
    text, count_ip = pattern_ip.subn(
        lambda m: m.group(1) + addresses + m.group(2), text
    )

    # 2. порт в MTDatacenterAddress(ip: $0, port: <port>, ...)
    pattern_port = re.compile(r'(MTDatacenterAddress\(ip: \$0,\s*port:\s*)[0-9]+')
    text, count_port = pattern_port.subn(
        lambda m: m.group(1) + port, text
    )

    if count_ip != 1 or count_port != 1:
        raise SystemExit(
            "ожидал по одному совпадению, получил ip=%d port=%d — патч 0001 не применён "
            "или upstream изменился" % (count_ip, count_port)
        )

    if text == original:
        print("уже настроено: %s:%s — изменений нет" % (", ".join(filter(None, [host, alt])), port))
        return

    write_raw(target, text)
    print("сервер прошит: %s:%s в %s"
          % (", ".join(filter(None, [host, alt])), port, TARGET))


if __name__ == "__main__":
    main()
