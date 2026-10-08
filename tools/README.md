# Подготовка инструментов

Из корня проекта:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\Setup-tools.ps1
```

Скрипт загружает FModelCLI v1.0.2 из GitHub Releases, проверяет SHA-256 и получает публичные ключи из `yarik0chka/wuwa-keys`. Уже установленные файлы сохраняются; существующий EXE всё равно проверяется по хэшу. Для обновления ключей добавь `-RefreshKeys`.

Создаваемые файлы:

- `fmodel/FModelCLI.exe` — внешний экстрактор;
- `pakkeys.txt` — публичные ключи игровых ресурсов;
- `fmodel/.data/` — зависимости, которые создаёт сам экстрактор при запуске.

Эти файлы исключены из Git. Лицензии и NOTICE находятся в `fmodel/`; происхождение описано в [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

Скрипт не запускает скачанный EXE и не меняет установку игры.
