# Внешние инструменты и источники

## FModelCLI

- Проект: https://github.com/Herselfta/FModelCLI
- Проверенный релиз: [v1.0.2](https://github.com/Herselfta/FModelCLI/releases/tag/v1.0.2).
- SHA-256 `FModelCLI.exe`: `86426493c63f0af2ccf6d1d8b498a737723069f6c25a573a46e94d1a3f26e835`.
- Лицензия: GPL-3.0; оригинальные [LICENSE](tools/fmodel/LICENSE), [NOTICE](tools/fmodel/NOTICE) и [описание лицензий](tools/fmodel/LICENSE_COMPLIANCE.md) сохранены без изменений.
- Соответствующие исходники: [дерево v1.0.2](https://github.com/Herselfta/FModelCLI/tree/v1.0.2), включая зависимости и подмодули проекта. Для получения полного дерева: `git clone --recurse-submodules --branch v1.0.2 https://github.com/Herselfta/FModelCLI.git`. Инструкции сборки находятся в README этого проекта.

WuwaRu вызывает FModelCLI отдельным процессом для чтения игровых ресурсов и независимой проверки собственного пакета. Бинарник не хранится в Git и не включается в публичную сборку; `tools/Setup-tools.ps1` получает его непосредственно из указанного релиза и проверяет хэш.

## Публичные ключи ресурсов

Источник: [yarik0chka/wuwa-keys](https://github.com/yarik0chka/wuwa-keys), `keys.json`. Установщик преобразует `mainKey` и `dynamicKeys[].key` в локальный `tools/pakkeys.txt`. Этот файл не отслеживается Git.

## Описание формата пакета

Собственный `wuwa_pak.py` записывает WuWa V12 без сжатия и шифрования. Формат сверялся с:

- [CUE4Parse](https://github.com/FabianFG/CUE4Parse): FPakEntry и PakFileReader.
- [WuwaIDLauncher / WuwaPakPacker.cs](https://github.com/Arkael-Dev/WuwaIDLauncher/blob/main/WuwaPakPacker.cs).

Готовые переводы сторонних русификаторов не копировались. `repak` не требуется и не входит в проект.

## Сборка приложения

PyInstaller используется только для сборки EXE. Его лицензия и исключение для загрузчика: https://pyinstaller.org/en/stable/license.html. Исходники WuwaRu включаются в создаваемый архив; игровые данные по умолчанию исключены.
