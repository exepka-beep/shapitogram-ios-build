#!/usr/bin/env python3
"""Проверка патча 0001 без upstream: счётчики строк в заголовках хунков.

`git apply` отвергает патч, если `@@ -a,b +c,d @@` расходится с реальным числом
строк в хунке ("corrupt patch"). Ошибка вылезает только в CI, после клона
upstream, — то есть через минуты. Этот скрипт ловит её локально и мгновенно.

Проверяет и сами заголовки, и то, что старые строки (`-` и контекст) стыкуются
с новыми (`+` и контекст) без расхождений в контексте.
"""

import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent


def find_pipeline_root(start):
    """Каталог конвейера iOS — тот, где лежит .github/workflows/build-unsigned-ipa.yml.

    Локально это ``shapitogram/ios`` (и ``tools/`` лежит рядом с ним), а в
    репозитории сборки ``ios/`` разворачивается в корень. Поэтому ищем вверх по
    дереву, проверяя оба варианта, — тогда один и тот же скрипт работает и там,
    и там.
    """
    marker = pathlib.Path(".github") / "workflows" / "build-unsigned-ipa.yml"
    for ancestor in [start] + list(start.parents):
        for candidate in (ancestor, ancestor / "ios"):
            if (candidate / marker).is_file():
                return candidate
    raise SystemExit("не нашёл каталог конвейера iOS: нигде выше нет %s" % marker)


PATCH = find_pipeline_root(HERE) / "patches" / "0001-shapitogram-branding-and-server.patch"

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

lines = PATCH.read_text(encoding="utf-8").splitlines()
problems = []
hunks = 0
in_hunk = False
old_count = new_count = 0
old_start = new_start = 0
header_old = header_new = 0
files = 0

for number, line in enumerate(lines, 1):
    if line.startswith("diff --git "):
        files += 1
        in_hunk = False
        continue

    match = HUNK_RE.match(line)
    if match:
        if in_hunk:
            if old_count != header_old or new_count != header_new:
                problems.append(
                    "хунк у строки %d: заголовок обещал -%d/+%d, а в теле -%d/+%d"
                    % (old_start, header_old, header_new, old_count, new_count)
                )
        hunks += 1
        old_start = number
        header_old = int(match.group(2)) if match.group(2) else 1
        header_new = int(match.group(4)) if match.group(4) else 1
        old_count = new_count = 0
        in_hunk = True
        continue

    if not in_hunk:
        continue

    if line.startswith("\\"):
        # "\ No newline at end of file" — не считается ни в одну сторону.
        continue
    if line.startswith("+"):
        new_count += 1
    elif line.startswith("-"):
        old_count += 1
    elif line.startswith(" ") or line == "":
        # Пустая строка внутри хунка = контекстная строка из одного пробела,
        # который редактор срезал. Считаем её контекстом.
        old_count += 1
        new_count += 1
    else:
        problems.append("строка %d: неожиданное начало %r внутри хунка"
                        % (number, line[:20]))

if in_hunk and (old_count != header_old or new_count != header_new):
    problems.append("последний хунк: заголовок обещал -%d/+%d, а в теле -%d/+%d"
                    % (header_old, header_new, old_count, new_count))

print("файлов в патче: %d, хунков: %d" % (files, hunks))

# Ключевые строки, которые обязаны быть в патче: без них сборка соберётся,
# но клиент уйдёт на чужие дата-центры или на старый сервер.
#
# Bundle id здесь намеренно НЕ проверяется: в патче он остаётся шаблоном
# {telegram_bundle_id}, а конкретное значение (CUSTOM_BUNDLE_ID) подставляется
# на этапе сборки артефакта, когда шаг Collect artifacts переписывает
# ph.telegra.Telegraph в Info.plist готового .app. Проверяем, что шаблон цел.
body = "\n".join(lines)
for needle, why in (
    ('2: ["94.156.170.106"]', "seed-адрес ShapitoGram"),
    ("port: 2398", "порт нашего MTProto-сервера"),
    ("shapitogram", "URL-схема"),
    ("ShapitoGram", "имя приложения"),
    ("{telegram_bundle_id}", "bundle id должен остаться шаблоном"),
):
    if needle not in body:
        problems.append("в патче нет %r (%s)" % (needle, why))

# Чужой сервер не должен остаться ни в одной форме.
for stale in ("2.27.200.203", "xtreegram", "Xtreegram", "XTree"):
    if stale in body:
        problems.append("в патче осталось от XTree Gram: %r" % stale)

print()
if problems:
    for problem in problems:
        print("PROBLEM: %s" % problem)
    sys.exit(1)
print("патч 0001 консистентен: счётчики хунков сходятся, чужого сервера нет")
