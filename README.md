# ShapitoGram — iOS build

Собирает **unsigned `.ipa`** клиента ShapitoGram из upstream Telegram-iOS прямо в GitHub Actions.
Подписи нет намеренно: `.ipa` подписывается при установке вашим Apple ID
(Sideloadly / AltStore / 3uTools), платный Developer Account не нужен.

Готовый клиент подключается **только к нашему серверу** — адрес и порт задаются
переменными `CUSTOM_HOST` / `CUSTOM_PORT` в workflow, а не правкой кода.

> Этот конвейер — переделка конвейера XTree Gram. История отладки (пять подводных
> камней самосборки, разбор крашлогов, замеры времени сборки) лежит рядом в
> `README-xtreegram-reference.md` — грабли те же самые, читать полезно.

## Что здесь лежит

| Файл | Что делает |
| --- | --- |
| `.github/workflows/build-unsigned-ipa.yml` | Весь конвейер: клон upstream → патч → адрес сервера → ключ → Xcode → сборка → чистка → zip |
| `scripts/apply_mods.sh` | Накладывает патч (сначала `--check`, чтобы устаревший патч падал громко) и запускает остальные фиксы |
| `scripts/apply_server.py` | Прошивает `CUSTOM_HOST` / `CUSTOM_HOST_ALT` / `CUSTOM_PORT` в seed-адрес клиента |
| `scripts/fetch_server_key.py` | Скачивает публичный RSA-ключ сервера из `/owpengram/server-info` |
| `scripts/apply_rsa_key.py` | Вшивает этот ключ в `defaultPublicKeys()` |
| `scripts/apply_app_group_fallback.py` | Учит клиент работать без App Group (его не даёт бесплатный Apple ID) |
| `scripts/apply_buildconfig_guard.py` | Убирает `NULL` из литерала `NSDictionary` в `BuildConfig.m` — иначе мгновенный SIGABRT |
| `scripts/apply_intro_texture_guard.py` | Не грузит PNG-текстуры первого экрана (падали в `__PNGReadPlugin`) |
| `scripts/apply_intro_disable.py` | Не поднимает OpenGL-машинерию интро — там ловился второй краш |
| `scripts/apply_splash_auto_advance.py` | Даёт пройти первый экран, когда интро уже не рисуется |
| `scripts/apply_graphics_probe_guard.py` | Уводит 1×1-пробу графического контекста на легаси-ветку |
| `scripts/apply_clouddata_guard.py` | Не даёт CloudKit упасть на `CKContainer.default()` без entitlement |
| `scripts/apply_siri_guard.py` | Отключает Siri — `INPreferences` бросает исключение без entitlement |
| `scripts/slim_ipa.sh` | Выкидывает лишние расширения, локали, символы |
| `patches/0001-shapitogram-branding-and-server.patch` | Брендинг (имя, bundle id, URL-схемы) + сид-адрес |
| `config/server-rsa-public.pem` | Публичный RSA-ключ сервера — **заглушка**, заполняется перед сборкой |
| `check_pipeline.py` | Проверяет YAML, env, файлы шагов и сам вызывает `tools/check_patch.py` |
| `tools/check_patch.py` | Счётчики строк в `@@`-заголовках патча — иначе `corrupt patch` только в CI |
| `tools/test_apply_server.py` | 7 сценариев прошивки адреса сервера |
| `tools/run_build.py` | Заливка + запуск workflow + ожидание + скачивание артефакта (в репозиторий не попадает) |
| `push_to_github.py` | Заливает содержимое этого каталога в репозиторий сборки (в сам репозиторий не попадает) |

## Порядок запуска

### 1. Токен GitHub

Токен нужен, чтобы залить конвейер и запустить сборку. Где взять:

1. Открыть **https://github.com/settings/tokens** → *Generate new token* → **classic**.
2. Отметить галочки:
   - **`repo`** — заливать файлы в репозиторий;
   - **`workflow`** — трогать файлы в `.github/workflows/`.
     🔴 **Без неё не обойтись:** GitHub запрещает создавать и менять воркфлоу
     токеном без этого scope и отказывает **только на этом одном файле** — то есть
     уже после того, как остальные 18 уехали. Поэтому `push_to_github.py` проверяет
     scope'ы заранее (`X-OAuth-Scopes`) и падает до заливки.
3. Срок — короткий (7–30 дней): токен даёт полный доступ к аккаунту. После сборки
   его лучше отозвать.
4. Положить токен в `ios/.gh_token` (одной строкой) — файл в список загрузки не
   входит и в репозиторий не попадает. Либо передать `--token` / `$GH_TOKEN`.

Fine-grained токен тоже подойдёт: **Contents = Read and write**, **Workflows = Read
and write**, и **Administration = Read and write**, если пользуешься `--create`.

### 2. Репозиторий сборки

Создать на GitHub пустой репозиторий (например `exepka-beep/shapitogram-ios-build`).
**Публичный** — иначе macOS-минуты Actions тарифицируются ×10, а бесплатных 2000 минут
в месяц хватает всего на 2–3 сборки. Секретов в репозитории нет: в патче только
брендинг и адрес сервера, который и так виден по DNS.

```sh
export GH_TOKEN=<classic PAT со scope repo и workflow>
python push_to_github.py --create --public --owner <owner> --repo <repo>
```

`--create` можно не указывать, если репозиторий уже существует.
Проверить, что зальётся: `python push_to_github.py --list`.

### 3. Сервер

Сборка должна знать **IP/домен** сервера и его **публичный RSA-ключ**. Ключ появляется
только после первого старта сервера (`TELESRV_RSA_IDENTITY_MODE=generated` — сервер
генерирует его сам), поэтому порядок такой: сначала поднять сервер, потом собирать клиент.

В workflow заполнено так:

```yaml
CUSTOM_HOST: shapitogram.xyz
CUSTOM_HOST_ALT: 94.156.170.106                            # fallback, можно убрать
CUSTOM_PORT: "2398"
SERVER_INFO_URL: "https://shapitogram.xyz/owpengram/server-info"   # либо пусто
```

**Почему два адреса.** В Telegram `seedAddressList` — это *список* на дата-центр, и
MtProtoKit честно перебирает его целиком (`MTDiscoverConnectionSignals`
`discoverSchemeWithContext:...addressList:` строит по пробнику на каждый адрес). Поэтому
вторая запись — настоящий резерв, а не украшение: домен переживает смену IP у хостера,
а голый IP выручает, если у пользователя не резолвится DNS. Потерять bootstrap-адрес
нельзя: без него клиент не доживёт до `help.getConfig`, где сервер отдаёт свой список.

**Домен в seed-адресе — это нормально.** Проверено по исходникам MtProtoKit:
`MTTcpConnection` передаёт строку из `address.ip` в `GCDAsyncSocket connectToHost:`,
а тот резолвит её через `getaddrinfo`. `inet_aton` там встречается только в ветке
SOCKS-прокси, которая у нас не задействована.

Если `SERVER_INFO_URL` пуст, шаг «Refresh the server RSA public key» пропускается и
ключ берётся из `config/server-rsa-public.pem` — туда его надо положить руками:

```sh
ssh -p 2222 root@<IP> \
  'docker exec $(docker ps -qf name=server) cat /var/lib/telesrv/server_rsa.pem' \
  > server_rsa.pem
openssl rsa -in server_rsa.pem -pubout > config/server-rsa-public.pem
python push_to_github.py
```

Пока файл остаётся заглушкой, шаг «Bake in the server RSA public key» **останавливает
сборку**: IPA с чужим ключом всё равно повиснет на чёрном сплэше, и отлаживать это
дороже, чем прочитать одну красную строку в логе.

**Что уже проверено (09.10.2026).** Эндпоинт `https://shapitogram.xyz/owpengram/server-info`
отвечает `200` и отдаёт `name=ShapitoGram`, `dc_id=2`. Фингерпринт, который считает
`fetch_server_key.py` (`0x1466b1b3af48f70b`), совпадает с `rsa_fingerprint` из логов
сервера (`1470057713681102603`) — значит вшивается ровно тот ключ, которым сервер
отвечает в `resPQ`. Формат ответа — PKCS#1 (`BEGIN RSA PUBLIC KEY`), и `apply_rsa_key.py`
его принимает наравне с SPKI.

### 4. Локальные проверки перед запуском

Сборку локально не прогнать (нужен macOS + Bazel), но всё, что можно проверить на
Linux, проверяется за секунды и экономит 60–90 минут раннера. Пути ниже — от корня
этого репозитория; в рабочей копии конвейер лежит в `ios/`, то есть там
`python ios/check_pipeline.py`.

```sh
python check_pipeline.py          # YAML, env, файлы шагов, патч, заглушка ключа
python tools/check_patch.py       # счётчики строк в @@-заголовках патча
python tools/test_apply_server.py # 7 сценариев прошивки адреса сервера
```

`check_pipeline.py` запускает `check_patch.py` сам, так что достаточно первого.
Счётчики хунков важны не для красоты: неверный `@@ -a,b +c,d @@` даёт `corrupt patch`
только в CI, уже после клона upstream. Оба скрипта в `tools/` сами находят каталог
конвейера, поэтому работают и здесь, и в рабочей копии.

### 5. Сборка

Через веб: Actions → **Build ShapitoGram Unsigned IPA** → *Run workflow*.

Или одной командой, без веб-интерфейса — `tools/run_build.py` заливает конвейер,
запускает workflow, следит за ним и скачивает артефакт:

```sh
python tools/run_build.py dispatch --create --public   # залить + запустить
python tools/run_build.py watch                        # ждать до конца
python tools/run_build.py download <run_id>            # скачать артефакт
```

Токен он берёт оттуда же, откуда `push_to_github.py`: `--token`, `$GH_TOKEN` или
файл `.gh_token` рядом с конвейером. В репозиторий сборки `run_build.py` не
заливается — он нужен только здесь.

Первая сборка идёт **60–90 минут** (Bazel тянет webrtc, tgcalls, td и компилирует их),
последующие быстрее за счёт кэша Bazel. По окончании — артефакт
`ShapitoGram-unsigned-ipa-<N>`.

Локально (нужен macOS + Xcode) то же самое:

```sh
git clone https://github.com/TelegramMessenger/Telegram-iOS.git src
git -C src checkout 6ad963e5b62d354da79040f388ae2b9132fb17b8
git -C src submodule update --init --recursive
./scripts/apply_mods.sh "$PWD/src"
CUSTOM_HOST=shapitogram.xyz CUSTOM_HOST_ALT=94.156.170.106 CUSTOM_PORT=2398 \
  python3 scripts/apply_server.py "$PWD/src"
python3 scripts/fetch_server_key.py --domain shapitogram.xyz --out config/server-rsa-public.pem
python3 scripts/apply_rsa_key.py "$PWD/src" config/server-rsa-public.pem
```

### 6. Установка на iPhone

1. Sideloadly (или AltStore) на компьютер.
2. Подключить iPhone, перетащить `.ipa`, ввести обычный Apple ID.
3. На телефоне: *Настройки → Основные → VPN и управление устройством* → доверять профилю.

**Бесплатный Apple ID = подпись живёт 7 дней**, потом переподписать. Платный аккаунт
(99 $/год) даёт год.

## Что меняет патч

Ровно два файла:

**`submodules/TelegramCore/Sources/Network/Network.swift`** — `seedAddressList` сведён к
одному DC 2, порт `443` → `2398`, убран `if testingEnvironment` (он уводил на тестовые
ДЦ Telegram). Конкретный адрес подставляется потом скриптом `apply_server.py`.

Сид-лист — только бутстрап: после первого `help.getConfig` сервер сам отдаёт клиенту
свой список адресов, поэтому в продовые ДЦ Telegram клиент не уходит.

**`Telegram/BUILD`** — `CFBundleDisplayName` / `CFBundleName` → `ShapitoGram`,
URL-схемы `telegram` / `tg` / `tonsite` → `shapitogram` / `shapitogram-compat` /
`shapitogram-site`. Bundle id (`com.shapitogram.messenger`) подставляется на этапе
сборки артефакта в `Collect artifacts`.

## Номер сборки

Upstream выводит `CFBundleVersion` из количества коммитов, поэтому все сборки одного
пинованного коммита носят один номер. Сдвигаем его в свой диапазон:

```sh
SHAPITOGRAM_BUILD_BASE=800000
BUILD_NUMBER=$((SHAPITOGRAM_BUILD_BASE + COMMIT_COUNT + BUILD_NUMBER_OFFSET))
```

`800000` выбран так, чтобы номера сборок ShapitoGram не пересекались с XTree Gram
(там `900000`): приложения разные, но так их не спутать в отчётах.

Номер дописывается в **имя** приложения намеренно: iOS нигде в интерфейсе не показывает
`CFBundleVersion`, поэтому без этого все сборки выглядят одинаково. Видно в
*Настройки → Основные → Хранилище iPhone* — например `ShapitoGram 834474`.

## Пять подводных камней самосборки

Коротко; подробный разбор с крашлогами — в `README-xtreegram-reference.md`.

| # | Что ломается | Фикс |
| --- | --- | --- |
| 1 | App Group недоступен бесплатному Apple ID → пустое окно | `apply_app_group_fallback.py` — фолбэк в свои Documents |
| 2 | Клиент не знает ключ сервера → рукопожатие не проходит | `apply_rsa_key.py` + `fetch_server_key.py` |
| 3 | Падение в PNG-декодере ImageIO на интро (~40 мс) | `apply_intro_texture_guard.py` + `apply_splash_auto_advance.py` |
| 4 | Падение в OpenGL-интро + `strip -x`, портящий рантайм Swift | `apply_intro_disable.py`, `strip -x` из `slim_ipa.sh` убран |
| 5 | Падение в 1×1-пробе `UIGraphicsImageRenderer` (стоковый код) | `apply_graphics_probe_guard.py` — перевод на легаси-ветку |

Плюс два страховочных: `apply_buildconfig_guard.py` (NULL в NSDictionary → мгновенный
SIGABRT), `apply_clouddata_guard.py` (CloudKit без entitlement → `brk #1`),
`apply_siri_guard.py` (Siri без entitlement → исключение после успешного логина).

## Обновление upstream

`UPSTREAM_REF` в workflow и патч жёстко связаны. При обновлении:

1. поднять `UPSTREAM_REF` до нового коммита,
2. локально прогнать `./scripts/apply_mods.sh <src>` — он скажет, если патч не ложится,
3. пересобрать патч под новый контекст (`git diff`), закоммитить оба изменения вместе.

## Что вырезано из `.ipa`

Расширения `Watch`, `Widget`, `BroadcastUpload`, `Share`, `Notification`, `Intents`
и все локали кроме `Base, en, ru` — чтобы архив был меньше и надёжнее подписывался
бесплатным Apple ID. Список правится переменными `IPA_DROP_PLUGINS` и
`IPA_KEEP_LOCALES` в workflow. Сборка только под **arm64** (реальные устройства).
