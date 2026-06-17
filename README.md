# Dota 2 Match Win Predictor

Проект для прогнозирования победителя матча Dota 2 по информации, известной до старта
игры: пики героев, рейтинг, патч и базовый контекст матча.

Текущий статус: реализована первая итерация parser MVP. Обучения модели, API сервиса и
feature engineering пока нет.

## Что уже реализовано

- Загрузка публичных матчей из OpenDota `/publicMatches`.
- Загрузка матчей через Valve Steam Web API:
  `GetMatchHistory` -> `GetMatchDetails`.
- Пагинация через `less_than_match_id`.
- Ограничение сбора по `collection_min_start_time`.
- Сбор последнего номерного patch family вместе с буквенными подпачами.
- Optional `OPENDOTA_API_KEY`.
- Retry/backoff для `429` и `5xx`.
- Идемпотентное сохранение raw JSON envelopes.
- Checkpoint для продолжения после остановки.
- Нормализация raw в `MatchRecord`.
- Фильтры качества для ranked All Pick.
- Запись normalized dataset в partitioned Parquet.
- JSONL-журнал отклонённых матчей.
- Тесты для collector, normalizer, raw store и Parquet writer.

## Структура

```text
configs/
  parser.yaml          # настройки источника, фильтров и путей
  patches.yaml         # справочник патчей
src/dota_predictor/
  parser/
    cli.py             # CLI entrypoint dota-parser
    source.py          # OpenDota HTTP client
    collector.py       # сбор /publicMatches
    raw_store.py       # immutable raw envelopes
    normalizer.py      # raw -> MatchRecord
    parquet_store.py   # MatchRecord -> Parquet
    patches.py         # PatchRegistry
    quality.py         # quality issues JSONL
    checkpoint.py      # resume state
    config.py          # ParserConfig
tests/parser/          # pytest suite
```

Generated data не коммитится:

```text
data/raw/opendota/public_matches/
data/raw/steam/match_details/
data/normalized/matches/
data/normalized/steam_matches/
artifacts/checkpoints/
artifacts/quality/
```

## Установка

Рекомендуемый способ - `uv`.

```bash
cd /home/dryu/gits/Dota-2-Match-Win-Predictor
uv sync --dev
```

Если `uv` ещё не установлен, можно временно использовать обычный venv:

```bash
cd /home/dryu/gits/Dota-2-Match-Win-Predictor
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Для разработки и проверок без `uv` также нужны dev-зависимости:

```bash
python -m pip install pytest ruff mypy types-PyYAML
```

## Быстрый запуск

Собрать и сразу нормализовать 100 матчей:

```bash
uv run dota-parser parse-public --limit 100
```

То же через активированный venv:

```bash
dota-parser parse-public --limit 100
```

Раздельный запуск:

```bash
uv run dota-parser collect-public --limit 100
uv run dota-parser normalize-public
```

Valve Steam Web API требует ключ:

```bash
export STEAM_WEB_API_KEY="your_key"
uv run dota-parser parse-steam --limit 100
```

Для модели полезнее свежая мета, поэтому основной рабочий сценарий - собрать последний
номерной патч и все его буквенные подпачи из `configs/patches.yaml`:

```bash
uv run dota-parser collect-public --all --latest-patch-family
uv run dota-parser normalize-public
```

Через Valve Steam Web API тот же сценарий:

```bash
export STEAM_WEB_API_KEY="your_key"
uv run dota-parser collect-steam --all --latest-patch-family
uv run dota-parser normalize-steam
```

Например, если последний номерной патч в registry - `7.39`, команда соберёт матчи с
начала `7.39` и захватит `7.39b`, `7.39c` и другие буквенные подпачи, пока они входят в
тот же patch family.

## CLI

Глобальные флаги указываются до команды:

```bash
uv run dota-parser [GLOBAL_FLAGS] <command> [COMMAND_FLAGS]
```

### Global flags

| Флаг | Default | Что делает |
| --- | --- | --- |
| `--config PATH` | `configs/parser.yaml` | Путь к конфигу parser. |
| `--patches PATH` | `configs/patches.yaml` | Путь к справочнику патчей. Используется при normalization. |
| `--log-level LEVEL` | `INFO` | Уровень логирования: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |

Пример:

```bash
uv run dota-parser --config configs/parser.yaml --log-level DEBUG collect-public --limit 500
```

### `collect-public`

Скачивает raw строки из OpenDota `/publicMatches` и сохраняет их в
`data/raw/opendota/public_matches/YYYY/MM/<match_id>.json`.

```bash
uv run dota-parser collect-public --limit 1000
```

Флаги:

| Флаг | Default | Что делает |
| --- | --- | --- |
| `--limit INT` | `100` | Максимум raw rows обработать за этот запуск. |
| `--all` | off | Собирать страницы до тех пор, пока OpenDota не вернёт пустую страницу. Нельзя использовать вместе с `--limit`. |
| `--patch-family PATCH` | off | Остановить сбор, когда parser дойдёт до матчей старше начала указанного номерного семейства, например `7.39`. |
| `--latest-patch-family` | off | Взять последнее номерное семейство из `configs/patches.yaml`; буквенные подпачи входят автоматически. |

### `normalize-public`

Читает все raw envelopes, фильтрует и пишет normalized Parquet.

```bash
uv run dota-parser normalize-public
```

Командных флагов нет. Использует `--config` и `--patches`.

### `collect-steam`

Скачивает матчи через Valve Steam Web API. Поток отличается от OpenDota:

1. `GetMatchHistory` возвращает страницу match ids и игроков.
2. Для каждого match id parser вызывает `GetMatchDetails`.
3. Raw response из `GetMatchDetails` сохраняется в
   `data/raw/steam/match_details/YYYY/MM/<match_id>.json`.

```bash
export STEAM_WEB_API_KEY="your_key"
uv run dota-parser collect-steam --limit 100
```

Флаги такие же, как у `collect-public`:

| Флаг | Default | Что делает |
| --- | --- | --- |
| `--limit INT` | `100` | Сколько match details сохранить за этот запуск. |
| `--all` | off | Идти по истории до пустого ответа, окончания query или patch cutoff. |
| `--patch-family PATCH` | off | Собирать только матчи с начала указанного номерного семейства. |
| `--latest-patch-family` | off | Собирать только последнее номерное семейство из patch registry. |

### `normalize-steam`

Читает raw Steam `GetMatchDetails` envelopes, фильтрует и пишет normalized Parquet в
`data/normalized/steam_matches`.

```bash
uv run dota-parser normalize-steam
```

### `parse-steam`

Shortcut: сначала `collect-steam`, затем `normalize-steam`.

```bash
export STEAM_WEB_API_KEY="your_key"
uv run dota-parser parse-steam --limit 100
```

### `parse-public`

Shortcut: сначала `collect-public`, затем `normalize-public`.

```bash
uv run dota-parser parse-public --limit 1000
```

Флаги такие же, как у `collect-public`:

| Флаг | Default | Что делает |
| --- | --- | --- |
| `--limit INT` | `100` | Сколько raw rows собрать перед normalization. |
| `--all` | off | Собирать до пустой страницы, затем нормализовать всё собранное. |
| `--patch-family PATCH` | off | Собирать только матчи с начала указанного номерного семейства. |
| `--latest-patch-family` | off | Собирать только последнее номерное семейство из patch registry. |

Для очень большого сбора лучше запускать `collect-public --all` отдельно, а
`normalize-public` уже после завершения или периодически вручную.

## Как спарсить последний patch family

Это рекомендуемый режим для MVP: данные ближе к текущей мете и дешевле по API/диску.

Сначала заполни `configs/patches.yaml` реальными границами последнего номерного патча и
его буквенных подпачей. Затем:

```bash
uv run dota-parser collect-public --all --latest-patch-family
uv run dota-parser normalize-public
```

Если хочешь явно указать семейство:

```bash
uv run dota-parser collect-public --all --patch-family 7.39
uv run dota-parser normalize-public
```

Для Valve Steam Web API:

```bash
export STEAM_WEB_API_KEY="your_key"
uv run dota-parser collect-steam --all --patch-family 7.39
uv run dota-parser normalize-steam
```

`--patch-family 7.39` означает: остановиться, когда сбор дошёл до матчей старше начала
`7.39`. Нормализация всё равно назначит точный `patch_id` по интервалам из
`configs/patches.yaml`: `7.39`, `7.39b`, `7.39c` и так далее.

Этот режим использует тот же checkpoint:

```text
artifacts/checkpoints/opendota_public.json
```

Если меняешь patch family или дату начала, лучше использовать отдельный `checkpoint_file`
и отдельный `raw_output_dir`, чтобы не смешивать разные сборы. Для Steam используются
отдельные настройки `steam_checkpoint_file` и `steam_raw_output_dir`.

## Как спарсить весь OpenDota

Полный сбор может быть очень долгим и большим по диску: OpenDota содержит миллионы
матчей, а parser сохраняет один raw envelope на матч. Используй этот режим только
осознанно.

Рекомендуемый вариант:

```bash
uv run dota-parser collect-public --all
```

После завершения или после большой порции raw:

```bash
uv run dota-parser normalize-public
```

Можно запустить одним shortcut, но normalization начнётся только когда сбор полностью
закончится:

```bash
uv run dota-parser parse-public --all
```

Checkpoint хранится здесь:

```text
artifacts/checkpoints/opendota_public.json
```

Если процесс остановить и запустить снова, parser продолжит с последнего сохранённого
`less_than_match_id`. Уже сохранённые raw files не перезаписываются.

Практические советы для полного сбора:

- Оставь `request_delay_seconds: 1.0`, чтобы не давить API.
- Если есть ключ OpenDota, добавь его в окружение:

```bash
export OPENDOTA_API_KEY="your_key"
```

- Запускай сбор в `tmux` или другой долгоживущей сессии.
- Следи за размером `data/raw/opendota/public_matches`.
- Не удаляй checkpoint, если хочешь продолжать, а не начинать сначала.
- Для обучения всё равно нужен корректный `configs/patches.yaml`, иначе `patch_id` будет
  только bootstrap или матчи попадут в quality issues при строгом каталоге.

## Конфигурация parser

Основной файл: `configs/parser.yaml`.

| Поле | Default | Что делает |
| --- | --- | --- |
| `source_base_url` | `https://api.opendota.com/api` | Base URL OpenDota API. |
| `public_matches_endpoint` | `/publicMatches` | Endpoint публичных матчей. |
| `steam_base_url` | `https://api.steampowered.com` | Base URL Valve Steam Web API. |
| `steam_match_history_endpoint` | `/IDOTA2Match_570/GetMatchHistory/v1/` | Endpoint для страниц match history. |
| `steam_match_details_endpoint` | `/IDOTA2Match_570/GetMatchDetails/v1/` | Endpoint для подробностей матча. |
| `steam_matches_requested` | `100` | Сколько history rows просить у `GetMatchHistory` за страницу. |
| `steam_history_game_mode` | `22` | Фильтр `game_mode` для Steam history. `22` = Ranked Matchmaking. |
| `steam_history_min_players` | `10` | Фильтр `min_players` для Steam history. |
| `request_delay_seconds` | `1.0` | Пауза после успешного запроса. |
| `max_retries` | `5` | Максимум повторов для retryable ошибок. |
| `backoff_initial_seconds` | `1.0` | Начальная задержка exponential backoff. |
| `backoff_max_seconds` | `30.0` | Максимальная задержка backoff. |
| `timeout_seconds` | `20.0` | HTTP timeout. |
| `min_rank` | `null` | Передаётся в OpenDota как `min_rank`, если задано. |
| `max_rank` | `null` | Передаётся в OpenDota как `max_rank`, если задано. |
| `collection_min_start_time` | `null` | ISO datetime cutoff. Collector сохраняет только матчи с `start_time >=` этому значению и останавливается, когда доходит до более старых матчей. |
| `allowed_game_modes` | `[22]` | Разрешённые режимы. `22` = All Pick. |
| `allowed_lobby_types` | `[7]` | Разрешённые lobby types. `7` = ranked. |
| `min_duration_seconds` | `600` | Матчи короче отклоняются. |
| `raw_output_dir` | `data/raw/opendota/public_matches` | Куда писать raw envelopes. |
| `steam_raw_output_dir` | `data/raw/steam/match_details` | Куда писать raw Steam `GetMatchDetails` envelopes. |
| `normalized_output_dir` | `data/normalized/matches` | Куда писать Parquet. |
| `steam_normalized_output_dir` | `data/normalized/steam_matches` | Куда писать normalized Steam Parquet. |
| `checkpoint_file` | `artifacts/checkpoints/opendota_public.json` | Resume checkpoint. |
| `steam_checkpoint_file` | `artifacts/checkpoints/steam_match_history.json` | Resume checkpoint для Steam history. |
| `quality_issues_file` | `artifacts/quality/public_matches_issues.jsonl` | Журнал отклонённых матчей. |
| `steam_quality_issues_file` | `artifacts/quality/steam_match_details_issues.jsonl` | Журнал отклонённых Steam матчей. |
| `schema_version` | `1` | Версия raw/normalized схемы. |

## Patch registry

Файл `configs/patches.yaml` хранит интервалы патчей:

```yaml
patches:
  - patch_id: "7.39"
    version: "7.39"
    started_at: "2025-05-22T00:00:00Z"
    ended_at: "2025-06-10T00:00:00Z"
    major: true
  - patch_id: "7.39b"
    version: "7.39b"
    started_at: "2025-06-10T00:00:00Z"
    ended_at: null
    major: false
```

Правило назначения:

```text
patch.started_at <= match.start_time < patch.ended_at
```

Сейчас в репозитории лежит bootstrap interval. Перед реальным обучением его нужно заменить
на проверенные даты патчей Dota 2.

Patch family - это номерной патч и все буквенные подпачи с тем же префиксом. Например:

```text
7.39 family = 7.39, 7.39b, 7.39c, 7.39d
```

`--latest-patch-family` ищет последний `patch_id` формата `N.NN`, например `7.39`, и
использует начало этого патча как cutoff для сбора.

## Фильтры качества

Матч не попадёт в normalized Parquet, если найдено одно из условий:

- неизвестный патч;
- не ровно 5 героев за Radiant или Dire;
- повторяющийся hero id среди 10 героев;
- `hero_id = 0`;
- `radiant_win` отсутствует;
- `game_mode` не входит в `allowed_game_modes`;
- `lobby_type` не входит в `allowed_lobby_types`;
- `duration` меньше `min_duration_seconds`.

Причины записываются в:

```text
artifacts/quality/public_matches_issues.jsonl
```

## Проверки

Через `uv`:

```bash
uv run pytest
uv run ruff check
uv run mypy src
```

Через активированный venv:

```bash
python -m pytest
python -m ruff check
python -m mypy src
```

## Что пока не реализовано

- OpenDota детальный `/matches/{match_id}` parser.
- Hero registry.
- Реальные признаки для ML.
- Обучение моделей.
- FastAPI endpoint.
- Автоматическое обновление каталога патчей.
- Поддержка Dotabuff, STRATZ и Dota2ProTracker.
