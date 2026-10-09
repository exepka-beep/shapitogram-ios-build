#!/usr/bin/env python3
"""Регрессионный тест scripts/apply_server.py из конвейера iOS.

Зачем
-----
Сборку iOS локально не прогнать (нужен macOS + Bazel), а `apply_server.py` —
единственный шаг конвейера, который правит код клиента на лету и при этом
переписывался руками. Ошибка в нём стоит 60–90 минут раннера, поэтому шаг
проверяется здесь на синтетическом Network.swift.

Фикстура создаётся в временном каталоге при каждом запуске, поэтому тест
самодостаточен и ничего в репозитории не трогает.

Запуск
------
    python tools/test_apply_server.py
"""

import os
import pathlib
import re
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
TARGET_REL = "submodules/TelegramCore/Sources/Network/Network.swift"


def find_pipeline_root(start):
    """Каталог конвейера iOS — тот, где лежит .github/workflows/build-unsigned-ipa.yml.

    Локально это ``shapitogram/ios`` (и ``tools/`` лежит рядом с ним), а в
    репозитории сборки ``ios/`` разворачивается в корень. Поэтому ищем вверх по
    дереву, проверяя оба варианта, — тогда один и тот же тест работает и там,
    и там.
    """
    marker = pathlib.Path(".github") / "workflows" / "build-unsigned-ipa.yml"
    for ancestor in [start] + list(start.parents):
        for candidate in (ancestor, ancestor / "ios"):
            if (candidate / marker).is_file():
                return candidate
    raise SystemExit("не нашёл каталог конвейера iOS: нигде выше нет %s" % marker)


SCRIPT = find_pipeline_root(HERE) / "scripts" / "apply_server.py"

# Ровно то, что оставляет после себя патч 0001: один адрес и порт 2398.
FIXTURE = """\
            let seedAddressList: [Int: [String]]
            
            // ShapitoGram: this build talks to our own MTProto server and nothing
            // else.
            seedAddressList = [
                2: ["94.156.170.106"]
            ]
            
            for (id, ips) in seedAddressList {
                context.setSeedAddressSetForDatacenterWithId(id, seedAddressSet: MTDatacenterAddressSet(addressList: ips.map { MTDatacenterAddress(ip: $0, port: 2398, preferForMedia: false, restrictToTcp: false, cdn: false, preferForProxy: false, secret: nil) }))
            }
            
            context.keychain = keychain
"""

ADDR_RE = re.compile(r'seedAddressList\s*=\s*\[\s*\d+:\s*\[([^\]]*)\]')
PORT_RE = re.compile(r'MTDatacenterAddress\(ip: \$0,\s*port:\s*(\d+)')

failures = []


def check(label, ok, detail=""):
    print("  %-44s %s %s" % (label, "OK " if ok else "FAIL", detail))
    if not ok:
        failures.append(label)


def main():
    if not SCRIPT.is_file():
        raise SystemExit("нет %s" % SCRIPT)

    with tempfile.TemporaryDirectory(prefix="shapitogram-applyserver-") as work:
        source_dir = pathlib.Path(work)
        target = source_dir / TARGET_REL
        target.parent.mkdir(parents=True, exist_ok=True)

        def reset():
            with open(target, "w", encoding="utf-8", newline="") as handle:
                handle.write(FIXTURE)

        def read():
            with open(target, "r", encoding="utf-8", newline="") as handle:
                return handle.read()

        def run(extra):
            env = dict(os.environ)
            for key in ("CUSTOM_HOST", "CUSTOM_HOST_ALT", "CUSTOM_PORT"):
                env.pop(key, None)
            env.update(extra)
            proc = subprocess.run([sys.executable, str(SCRIPT), str(source_dir)],
                                  capture_output=True, text=True, env=env)
            return proc.returncode, (proc.stdout + proc.stderr).strip()

        def addresses():
            return ADDR_RE.search(read()).group(1).strip()

        def port():
            return PORT_RE.search(read()).group(1)

        print("=== 1. домен + IP как fallback ===")
        reset()
        rc, out = run({"CUSTOM_HOST": "shapitogram.xyz",
                       "CUSTOM_HOST_ALT": "94.156.170.106",
                       "CUSTOM_PORT": "2398"})
        print("   rc=%d  %s" % (rc, out))
        check("rc == 0", rc == 0)
        check("домен первым, IP вторым",
              addresses() == '"shapitogram.xyz", "94.156.170.106"', addresses())
        check("порт 2398", port() == "2398", port())

        print("=== 2. повторный запуск идемпотентен ===")
        before = read()
        rc, out = run({"CUSTOM_HOST": "shapitogram.xyz",
                       "CUSTOM_HOST_ALT": "94.156.170.106",
                       "CUSTOM_PORT": "2398"})
        print("   rc=%d  %s" % (rc, out))
        check("rc == 0", rc == 0)
        check("файл не изменился", read() == before)
        check("сказал, что менять нечего", "изменений нет" in out)

        print("=== 3. без CUSTOM_HOST_ALT — один адрес ===")
        reset()
        rc, out = run({"CUSTOM_HOST": "shapitogram.xyz", "CUSTOM_PORT": "2398"})
        print("   rc=%d  %s" % (rc, out))
        check("rc == 0", rc == 0)
        check("ровно один адрес", addresses() == '"shapitogram.xyz"', addresses())

        print("=== 4. пустой CUSTOM_HOST — отказ ===")
        reset()
        rc, out = run({"CUSTOM_HOST": "", "CUSTOM_PORT": "2398"})
        print("   rc=%d  %s" % (rc, out))
        check("rc != 0", rc != 0)
        check("файл не тронут", read() == FIXTURE)

        print("=== 5. инъекция через CUSTOM_HOST — отказ ===")
        reset()
        rc, out = run({"CUSTOM_HOST": 'a"]; let x = ["',
                       "CUSTOM_PORT": "2398"})
        print("   rc=%d  %s" % (rc, out))
        check("rc != 0", rc != 0)
        check("файл не тронут", read() == FIXTURE)

        print("=== 6. ALT совпадает с HOST — отказ ===")
        reset()
        rc, out = run({"CUSTOM_HOST": "shapitogram.xyz",
                       "CUSTOM_HOST_ALT": "shapitogram.xyz",
                       "CUSTOM_PORT": "2398"})
        print("   rc=%d  %s" % (rc, out))
        check("rc != 0", rc != 0)

        print("=== 7. CUSTOM_PORT не число — отказ ===")
        reset()
        rc, out = run({"CUSTOM_HOST": "shapitogram.xyz", "CUSTOM_PORT": "abc"})
        print("   rc=%d  %s" % (rc, out))
        check("rc != 0", rc != 0)

    print()
    if failures:
        print("ПРОВАЛЫ: %s" % ", ".join(failures))
        return 1
    print("все проверки apply_server.py пройдены")
    return 0


if __name__ == "__main__":
    sys.exit(main())
