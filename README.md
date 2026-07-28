# CZ Async

Внутренний сервис автоматизированного получения, обработки и хранения данных ГИС МТ.

Система выполняет авторизацию организаций через сертификаты электронной подписи, формирует задания синхронизации, получает данные ГИС МТ и сохраняет результаты в MySQL.

## Архитектура

```text
Control Web
    |
    v
Pipeline Dispatcher
    |
    v
Windows Certificate Agent
    |
    v
RabbitMQ
    |
    v
Sync Worker
    |
    v
MySQL
```

| Компонент | Среда | Назначение |
|---|---|---|
| `control-web` | Docker | Панель управления, настройки и ручной запуск |
| `pipeline-dispatcher` | Docker | Управление последовательностью авторизации и синхронизации |
| `schema-migrate` | Docker | Автоматическое применение миграций MySQL |
| `mysql` | Docker | Основное хранилище данных |
| `rabbitmq` | Docker | Очередь заданий |
| `certificate_agent.py` | Windows | Работа с сертификатами и DistKontrol в интерактивной сессии |
| `sync-worker` | Docker, профиль `tools` | Выполнение заданий синхронизации |

Certificate Agent должен работать в интерактивной Windows-сессии пользователя, имеющего доступ к сертификатам и закрытым ключам.

## Локальные адреса

| Сервис | Адрес |
|---|---|
| Панель управления | `http://127.0.0.1:18080` |
| Health Control Web | `http://127.0.0.1:18080/api/health` |
| Health Certificate Agent | `http://127.0.0.1:18771/health` |
| RabbitMQ Management | `http://127.0.0.1:15672` |
| MySQL | `127.0.0.1:3306` |

Сервисы публикуются только на loopback-интерфейсе.

## Требования

- Windows 10 или Windows 11;
- Docker Desktop;
- Python 3.12;
- Windows PowerShell 5.1;
- действующие сертификаты электронной подписи;
- установленный и настроенный DistKontrol;
- доступ к ГИС МТ;
- заполненный файл `.env`.

## Настройка окружения

```powershell
Copy-Item `
    .\.env.example `
    .\.env
```

Файл `.env` содержит секреты и не должен добавляться в Git.

```powershell
git check-ignore -v .env
```

## Certificate Agent

Регистрация задания Windows:

```powershell
& .\tools\register_certificate_agent_task.ps1
```

Имя задания:

```text
CZ Async Certificate Agent
```

Запуск:

```powershell
Start-ScheduledTask `
    -TaskName "CZ Async Certificate Agent"
```

Проверка:

```powershell
Invoke-RestMethod `
    -Method Get `
    -Uri "http://127.0.0.1:18771/health" |
ConvertTo-Json -Depth 5
```

## Запуск Docker-контура

Проверка конфигурации:

```powershell
docker compose `
    --ansi never `
    --env-file .env `
    config `
    --quiet
```

Сборка и запуск:

```powershell
docker compose `
    --ansi never `
    --env-file .env `
    up `
    -d `
    --build `
    control-web `
    pipeline-dispatcher
```

Порядок запуска:

1. MySQL переходит в состояние `healthy`.
2. `schema-migrate` применяет миграции.
3. `schema-migrate` завершается с кодом `0`.
4. Запускаются `control-web` и `pipeline-dispatcher`.

Состояние `Exited (0)` для `schema-migrate` является штатным.

## Проверка состояния

```powershell
docker compose `
    --ansi never `
    --env-file .env `
    ps
```

В рабочем состоянии должны быть запущены:

```text
gis-mt-mysql
gis-mt-rabbitmq
gis-mt-control-web
gis-mt-pipeline-dispatcher
```

Проверка панели:

```powershell
Invoke-RestMethod `
    -Method Get `
    -Uri "http://127.0.0.1:18080/api/health"
```

Проверка диспетчера:

```powershell
docker compose `
    --ansi never `
    --env-file .env `
    logs `
    --no-color `
    --tail 100 `
    pipeline-dispatcher
```

Ожидаемые сообщения:

```text
Docker-диспетчер запущен.
Certificate-agent доступен
```

## Миграции MySQL

Файлы миграций расположены в каталоге:

```text
apps/sync_worker/migrations
```

Ручной запуск:

```powershell
docker compose `
    --ansi never `
    --env-file .env `
    up `
    --force-recreate `
    schema-migrate
```

Проверка статуса:

```powershell
docker compose `
    --ansi never `
    --env-file .env `
    run `
    --rm `
    -T `
    --no-deps `
    --pull never `
    --entrypoint python `
    schema-migrate `
    -u `
    -m `
    app.schema_migrations `
    status
```

Недопустимые состояния:

```text
DRIFT
FAILED
APPLYING
ORPHANED
```

Параметр `--retry-incomplete` применяется только после ручной проверки частично выполненного DDL.

## Управление конвейером

Панель управления:

```text
http://127.0.0.1:18080
```

| Статус | Значение |
|---|---|
| `SUCCESS` | Все выбранные организации обработаны |
| `PARTIAL` | Часть организаций обработана, часть безопасно пропущена |
| `ERROR` | Получены ошибки обработки |

Если устройство DistKontrol занято другой организацией, задание авторизации получает статус `SKIPPED_BUSY`. Команды принудительного освобождения устройства автоматически не отправляются.

## Диагностика

Диагностические сценарии расположены в `tools/diagnostics`.

### MySQL с корректной кириллицей

```powershell
$sql = @'
SELECT
    last_test_message
FROM sys_pipeline_config
WHERE id = 1;
'@

$sql |
& .\tools\diagnostics\invoke_mysql_utf8.ps1 `
    -Table
```

Запуск SQL-файла:

```powershell
& .\tools\diagnostics\invoke_mysql_utf8.ps1 `
    -SqlFile .\query.sql `
    -Table
```

### Проверка сертификатов и DistKontrol

```powershell
& .\tools\diagnostics\test_diskontrol_access.ps1
```

Сценарий проверяет список настроенных организаций, сертификаты, закрытые ключи, срок действия, соответствие ИНН, получение токена True API и блокировку подписания.

## Журналы

```powershell
docker compose `
    --ansi never `
    --env-file .env `
    logs `
    --no-color `
    --tail 200 `
    pipeline-dispatcher
```

```powershell
docker compose `
    --ansi never `
    --env-file .env `
    logs `
    --no-color `
    --tail 200 `
    schema-migrate
```

```powershell
docker compose `
    --ansi never `
    --env-file .env `
    logs `
    --no-color `
    --tail 200 `
    control-web
```

## Перезапуск

```powershell
docker compose `
    --ansi never `
    --env-file .env `
    up `
    -d `
    --no-build `
    --pull never `
    --force-recreate `
    control-web `
    pipeline-dispatcher
```

```powershell
Stop-ScheduledTask `
    -TaskName "CZ Async Certificate Agent" `
    -ErrorAction SilentlyContinue

Start-Sleep -Seconds 2

Start-ScheduledTask `
    -TaskName "CZ Async Certificate Agent"
```

## Остановка

```powershell
docker compose `
    --ansi never `
    --env-file .env `
    stop `
    control-web `
    pipeline-dispatcher
```

Не использовать для рабочего контура:

```text
docker compose down -v
```

Параметр `-v` удаляет Docker volumes и может привести к потере базы MySQL и данных RabbitMQ.

## Развёртывание на чистой базе

Чистая база создаётся init-скриптами из `mysql/init`. После инициализации миграции приводят схему к актуальной версии.

В init-скриптах нет зашитых организаций, ИНН или сертификатов. Настройка юридических лиц выполняется отдельно после развёртывания.

Развёртывание на временном чистом volume проверено для миграций `0001`–`0012`.

## Структура проекта

```text
apps/
  control_web/
  sync_worker/
    app/
    migrations/

mysql/
  init/

tests/

tools/
  diagnostics/
    invoke_mysql_utf8.ps1
    test_diskontrol_access.ps1

  authorize_pipeline_entity.ps1
  certificate_agent.py
  diskontrol_device.ps1
  get_true_api_token.ps1
  register_certificate_agent_task.ps1

compose.yaml
.env.example
pyproject.toml
requirements-dev.txt
```

## Проверка качества

```powershell
python `
    -m venv `
    .venv
```

```powershell
.\.venv\Scripts\python.exe `
    -m pip install `
    -r requirements-dev.txt
```

```powershell
.\.venv\Scripts\python.exe `
    -m pytest `
    -q
```

```powershell
docker compose `
    --ansi never `
    --env-file .env `
    config `
    --quiet
```

## Безопасность

- секреты хранятся только в `.env`;
- `.env` исключён из Git;
- токены True API не сохраняются на диск;
- Certificate Agent работает только на `127.0.0.1`;
- сервисы Docker публикуются только на loopback-интерфейсе;
- пароли не должны выводиться в журналы и traceback;
- токены, пароли и закрытые ключи запрещено помещать в Git;
- после попадания секрета в консольный журнал секрет необходимо заменить.
