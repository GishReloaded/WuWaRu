from __future__ import annotations
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from translator import Cache, Provider, batches, check_cancel, translate_pending, translatable, localize_terms, localize_choices, choice_values

GAME_DEFAULT = r'D:\Games\steamapps\common\Wuthering Waves'
PAK_NAME = 'pakchunk0-WuwaRu_900_P.pak'
MOUNT_PREFIX = 'Lang_en/WuwaRu/pakchunk0-WuwaRu_900_P'

def atomic_json(path, obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(tmp,path)

def sha1(path):
    digest=hashlib.sha1()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            digest.update(block)
    return digest.hexdigest().upper()

def resource_root(game):
    root=game/'Client/Saved/Resources'
    candidates=[p for p in root.iterdir() if p.is_dir() and re.fullmatch(r'\d+(?:\.\d+)+',p.name) and (p/'Mount/MountResource.txt').exists()]
    if not candidates:
        raise RuntimeError('Не найдена активная версия ресурсов игры. Запусти официальный лаунчер и закончи обновление.')
    return max(candidates,key=lambda p:tuple(map(int,p.name.split('.'))))

def game_running():
    if os.name!='nt':
        return False
    out=subprocess.run(['tasklist','/FI','IMAGENAME eq Client-Win64-Shipping.exe','/FO','CSV','/NH'],capture_output=True,creationflags=0x08000000)
    return b'Client-Win64-Shipping.exe' in out.stdout

def steam_app_id(game):
    game=Path(game).resolve()
    if game.parent.name.lower()!='common': return None
    steamapps=game.parent.parent
    for manifest in steamapps.glob('appmanifest_*.acf'):
        text=manifest.read_text(encoding='utf-8',errors='replace')
        folder=re.search(r'"installdir"\s+"([^"\r\n]+)"',text)
        appid=re.search(r'"appid"\s+"(\d+)"',text)
        if folder and appid and folder.group(1).casefold()==game.name.casefold():
            return appid.group(1)
    return None

def run_tool(args, log_path, cancel):
    log_path.parent.mkdir(parents=True,exist_ok=True)
    with log_path.open('wb') as out:
        child=subprocess.Popen([str(x) for x in args],stdout=out,stderr=subprocess.STDOUT,creationflags=0x08000000 if os.name=='nt' else 0)
        while child.poll() is None:
            if cancel.wait(.2):
                child.terminate(); child.wait()
                check_cancel(cancel)
        if child.returncode:
            raise RuntimeError(f'Ошибка {Path(args[0]).name}. Подробности: {log_path}')

def quote_sql(name):
    return '"'+name.replace('"','""')+'"'

class Project:
    def __init__(self, home, config, log=print, cancelled=None):
        self.home=Path(home)
        self.config=config
        self.game=Path(config.get('game_path',GAME_DEFAULT))
        self.log=log
        self.cancelled=cancelled or threading.Event()
        self.data=self.home/'data'
        self.data.mkdir(parents=True,exist_ok=True)
        self.source=self.data/'source'
        self.tools=self.home/'tools'
        self.glossary=json.loads((self.home/'glossary.json').read_text(encoding='utf-8'))
        self.overrides=json.loads((self.home/'overrides.json').read_text(encoding='utf-8'))
        terms=self.home/'terms.json'
        self.terms=json.loads(terms.read_text(encoding='utf-8')) if terms.exists() else {}
        choices=self.home/'choices.json'
        self.choices=json.loads(choices.read_text(encoding='utf-8')) if choices.exists() else {}
    @contextmanager
    def lock(self):
        lockpath=self.data/'work.lock'
        stream=lockpath.open('a+b')
        if os.name=='nt':
            import msvcrt
            if lockpath.stat().st_size==0: stream.write(b'0'); stream.flush()
            stream.seek(0)
            try: msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:
                stream.close()
                raise RuntimeError('Другой экземпляр WuwaRu уже работает с этой папкой.')
        try: yield
        finally:
            if os.name=='nt':
                stream.seek(0); msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            stream.close()
    def validate(self):
        if not (self.game/'Wuthering Waves.exe').is_file():
            raise RuntimeError('Не найден Wuthering Waves.exe. Проверь путь к игре.')
        return resource_root(self.game)
    def official_paks(self, resources):
        # Include all base chunks: 3.7 puts newer split databases in another chunk.
        # Only manifest-listed patches are current. Our own output is excluded.
        result=list((self.game/'Client/Content/Paks').glob('*.pak'))
        for mount in ('MountResource.txt','MountLauncher.txt'):
            text=(resources/'Mount'/mount).read_text(encoding='utf-8-sig')
            section=False
            for line in text.splitlines():
                if line=='::Mount::': section=True; continue
                if line.startswith('::'): section=False; continue
                if section and ',' in line:
                    path=(resources/(line.split(',')[0]+'.pak')).resolve()
                    if not path.is_relative_to(resources.resolve()):
                        raise ValueError('Недопустимый путь в манифесте игры.')
                    if not path.is_file():
                        raise RuntimeError('Недостающий пакет игры: '+str(path))
                    result.append(path)
        if not result:
            raise RuntimeError('Не найдены пакеты игры.')
        return result
    def extract(self, force=False):
        resources=self.validate()
        paks=self.official_paks(resources)
        signature=hashlib.sha256(json.dumps([(str(p),p.stat().st_size,p.stat().st_mtime_ns) for p in paks]).encode()).hexdigest()
        stamp=self.data/'source-manifest.json'
        if not force and stamp.exists() and json.loads(stamp.read_text())['signature']==signature and (self.source/'lang_multi_text.db').is_file():
            self.log('Версия текстов не изменилась; использую локальные базы.')
            return resources
        self.log('Извлекаю английские базы из активных пакетов игры…')
        extractor=self.tools/'fmodel/FModelCLI.exe'
        keys=self.tools/'pakkeys.txt'
        if not extractor.is_file() or not keys.is_file():
            raise RuntimeError('Отсутствует tools/fmodel/FModelCLI.exe или tools/pakkeys.txt.')
        stage=self.data/'pak-input'
        if stage.exists(): shutil.rmtree(stage)
        stage.mkdir()
        if os.name=='nt':
            # Directory junctions work across drives and need no elevation.
            # Never copy the game's many gigabytes into the translator folder.
            for i,parent in enumerate(dict.fromkeys(p.parent for p in paks)):
                target=(stage/f'{i:03}').resolve()
                literal=lambda value:"'"+str(value).replace("'","''")+"'"
                script=f'New-Item -ItemType Junction -Path {literal(target)} -Target {literal(parent.resolve())} | Out-Null'
                run_tool(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],self.data/'junction.log',self.cancelled)
        else:
            for i,p in enumerate(paks):
                target=stage/f'{i:03}'/p.name
                target.parent.mkdir()
                target.symlink_to(p.resolve())
        raw=self.data/'extract-tmp'
        if raw.exists(): shutil.rmtree(raw)
        raw.mkdir()
        run_tool([extractor,stage,'@'+str(keys.resolve()),raw,'ConfigDB/en/lang_'],self.data/'extract.log',self.cancelled)
        extracted=raw/'Client/Content/Aki/ConfigDB/en'
        if not (extracted/'lang_multi_text.db').is_file():
            raise RuntimeError('Базы не извлечены. Нужен актуальный ключ пакетов/экстрактор; см. data/extract.log.')
        for path in extracted.glob('*.db'):
            with sqlite3.connect(path) as db:
                if db.execute('pragma quick_check').fetchone()[0]!='ok':
                    raise RuntimeError('Повреждённая исходная база: '+path.name)
        fresh=self.data/'source-new'
        if fresh.exists(): shutil.rmtree(fresh)
        shutil.copytree(extracted,fresh)
        if self.source.exists(): shutil.rmtree(self.source)
        fresh.rename(self.source)
        atomic_json(stamp,{'signature':signature,'resource_version':resources.name,'files':[str(p) for p in paks]})
        self.log(f'Извлечено {len(list(self.source.glob("*.db")))} баз.')
        return resources
    def rows(self):
        for path in sorted(self.source.glob('*.db')):
            with sqlite3.connect(f'{path.resolve().as_uri()}?mode=ro',uri=True) as db:
                for (table,) in db.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'"):
                    columns={row[1] for row in db.execute(f'pragma table_info({quote_sql(table)})')}
                    if not {'Id','Content'}.issubset(columns): continue
                    for identifier,source in db.execute(f'select Id, Content from {quote_sql(table)}'):
                        if isinstance(source,str) and source.strip():
                            yield path.name,table,identifier,source
    def sources(self):
        ranked={}
        for file,table,identifier,source in self.rows():
            override_key=f'{file}:{table}:{identifier}'
            if source in self.glossary or override_key in self.overrides or (table=='MultiText' and str(identifier) in self.overrides): continue
            key=str(identifier).lower()
            if 'ui' in file or 'menu' in file or key.startswith(('ui_','menutext_','hotpatch','prefabtextitem_','text_','menuconfig_',
                                                                        'functionmenu_','functioncondition_','uidynamictab_','keysetting_')):
                rank=0
            elif 'quest' in key or 'quest' in file:
                rank=1
            else: rank=2
            ranked[source]=min(rank,ranked.get(source,rank))
        return sorted(ranked,key=lambda s:(ranked[s],len(s),s))
    def translate(self, limit=0):
        self.extract()
        values={value for *_,source in self.rows() for value in choice_values(source)}
        missing=sorted(value for value in values if value not in self.choices and translatable(value))
        if limit: missing=missing[:limit]
        if missing:
            provider=Provider(self.config,self.cancelled)
            for batch in batches(missing):
                self.choices.update(zip(batch,provider.translate(batch)))
                atomic_json(self.home/'choices.json',self.choices)
            self.log(f'Переведено вариантов текста в шаблонах: {len(missing)}.')
        sources=self.sources()
        cache=Cache(self.data/'cache.sqlite3')
        try:
            return translate_pending(sources,cache,self.config,self.cancelled,self.log,limit)
        finally: cache.close()
    def build(self):
        resources=self.extract()
        cache=Cache(self.data/'cache.sqlite3')
        known=cache.all(); cache.close()
        stage=self.data/'package-stage'
        if stage.exists(): shutil.rmtree(stage)
        target=stage/'Client/Content/Aki/ConfigDB/en'
        shutil.copytree(self.source,target)
        translated=0; total=0; changed=0
        for path in sorted(target.glob('*.db')):
            check_cancel(self.cancelled)
            with sqlite3.connect(path) as db:
                for (table,) in db.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'").fetchall():
                    columns={row[1] for row in db.execute(f'pragma table_info({quote_sql(table)})')}
                    if not {'Id','Content'}.issubset(columns): continue
                    updates=[]
                    for identifier,source in db.execute(f'select Id, Content from {quote_sql(table)}').fetchall():
                        if not isinstance(source,str) or not source.strip(): continue
                        total+=1
                        russian=self.overrides.get(f'{path.name}:{table}:{identifier}',self.overrides.get(str(identifier)) if table=='MultiText' and str(identifier) in self.overrides else self.glossary.get(source,known.get(source)))
                        if russian is None and any(value in self.choices for value in choice_values(source)):
                            russian=source
                        if russian is not None:
                            russian=localize_terms(russian,self.terms)
                            russian=localize_choices(russian,self.choices)
                            translated+=1
                            if russian!=source:
                                updates.append((russian,identifier)); changed+=1
                    db.executemany(f'update {quote_sql(table)} set Content=? where Id=?',updates)
                db.commit()
                if db.execute('pragma quick_check').fetchone()[0]!='ok':
                    raise RuntimeError('Проверка собранной базы не прошла: '+path.name)
        output=self.home/'output'
        output.mkdir(exist_ok=True)
        tmp=output/'translation.tmp.pak'
        from wuwa_pak import pack
        pack(stage,tmp,self.cancelled)
        # Round-trip the package before replacing the last known output.
        check=self.data/'package-check'
        if check.exists(): shutil.rmtree(check)
        check_input=self.data/'package-input'
        if check_input.exists(): shutil.rmtree(check_input)
        check_input.mkdir()
        shutil.copy2(tmp,check_input/PAK_NAME)
        # Independent game-specific reader verifies the V12 entry permutation.
        run_tool([self.tools/'fmodel/FModelCLI.exe',check_input,
                  '@'+str((self.tools/'pakkeys.txt').resolve()),check,'ConfigDB/en/lang_'],
                 self.data/'package-check.log',self.cancelled)
        for path in target.glob('*.db'):
            other=check/'Client/Content/Aki/ConfigDB/en'/path.name
            if not other.is_file() or sha1(path)!=sha1(other):
                raise RuntimeError('Проверка пакета не прошла: '+path.name)
        final=output/PAK_NAME
        os.replace(tmp,final)
        sources=self.sources()
        pending=sum(s not in known and translatable(s) for s in sources)
        pending_choices=len({value for *_,source in self.rows() for value in choice_values(source)
                             if value not in self.choices and translatable(value)})
        meta={'created':int(time.time()),'resource_version':resources.name,'source_signature':json.loads((self.data/'source-manifest.json').read_text())['signature'],
              'databases':len(list(target.glob('*.db'))),'rows':total,'translated_rows':translated,'changed_rows':changed,'pending_unique_strings':pending,
              'pending_selector_values':pending_choices,'complete':pending==0 and pending_choices==0,
              'sha1':sha1(final),'game_verified':False,'pak_version':'WuWa-V12'}
        atomic_json(output/'manifest.json',meta)
        self.log(f'Пакет собран: {translated:,}/{total:,} непустых строк; осталось уникальных: {pending:,}.')
        return final
    def install(self):
        resources=self.extract()
        if game_running(): raise RuntimeError('Закрой игру перед установкой перевода.')
        output=self.home/'output'/PAK_NAME
        manifest=json.loads((output.parent/'manifest.json').read_text(encoding='utf-8'))
        current=json.loads((self.data/'source-manifest.json').read_text())
        # extract() at launch detects updates before this check.
        if manifest['resource_version']!=resources.name or manifest['source_signature']!=current['signature']:
            raise RuntimeError('Пакет устарел. Сначала собери перевод заново.')
        if sha1(output)!=manifest['sha1']: raise RuntimeError('Пакет изменён после сборки.')
        directory=resources/'Lang_en/WuwaRu'
        directory.mkdir(parents=True,exist_ok=True)
        dest=directory/PAK_NAME
        temp=dest.with_suffix('.tmp')
        shutil.copy2(output,temp); os.replace(temp,dest)
        mount=resources/'Mount/MountLang_en.txt'
        original=mount.read_bytes()
        backup=self.data/'backups'/resources.name
        backup.mkdir(parents=True,exist_ok=True)
        stamp=str(time.time_ns())
        (backup/(stamp+'-MountLang_en.txt')).write_bytes(original)
        changed=update_mount(original, f'{MOUNT_PREFIX},900,{sha1(dest)},,,')
        temp_mount=mount.with_suffix('.tmp')
        temp_mount.write_bytes(changed); os.replace(temp_mount,mount)
        atomic_json(self.data/'installed.json',{'resources':str(resources),'path':str(dest),'installed':int(time.time())})
        self.log('Пакет подключён к английскому языку. В игре выбери English.')
    def uninstall(self):
        if game_running(): raise RuntimeError('Закрой игру перед отключением перевода.')
        root=self.game/'Client/Saved/Resources'
        if not root.exists(): return
        for resources in root.iterdir():
            mount=resources/'Mount/MountLang_en.txt'
            if not mount.is_file(): continue
            old=mount.read_bytes(); new=update_mount(old,None)
            if old!=new:
                backup=self.data/'backups'/resources.name; backup.mkdir(parents=True,exist_ok=True)
                (backup/(str(time.time_ns())+'-uninstall-MountLang_en.txt')).write_bytes(old)
                temp=mount.with_suffix('.tmp'); temp.write_bytes(new); os.replace(temp,mount)
            pak=resources/'Lang_en/WuwaRu'/PAK_NAME
            if pak.exists(): pak.unlink()
        self.log('Собственный пакет отключён. Английский язык восстановлен.')
    def launch(self):
        if game_running(): raise RuntimeError('Игра уже запущена.')
        appid=steam_app_id(self.game) if self.config.get('launch_mode','auto')=='auto' else None
        if appid and os.name=='nt':
            os.startfile(f'steam://run/{appid}')
            self.log('Отправлен штатный запрос запуска игры через Steam.')
            return
        relative=self.config.get('launch_executable','Wuthering Waves.exe')
        executable=(self.game/relative).resolve()
        if not executable.is_relative_to(self.game.resolve()) or not executable.is_file():
            raise RuntimeError('Не найден настроенный исполняемый файл игры.')
        args=self.config.get('launch_args',['-dx12'])
        if not isinstance(args,list) or not all(isinstance(a,str) for a in args):
            raise ValueError('launch_args должен быть списком строк.')
        try:
            subprocess.Popen([str(executable),*args],cwd=self.game)
        except OSError as error:
            if os.name!='nt' or getattr(error,'winerror',None)!=740: raise
            self.log('Игра требует права администратора. Подтверди стандартное окно Windows UAC.')
            try:
                os.startfile(str(executable),'runas',subprocess.list2cmdline(args),str(self.game))
            except OSError as elevated:
                if getattr(elevated,'winerror',None)==1223:
                    raise RuntimeError('Запуск игры отменён в окне Windows. Пакет и кэш сохранены.') from elevated
                raise
        self.log('Запущен '+executable.name+'.')

def update_mount(raw: bytes, entry: str | None):
    bom=raw.startswith(b'\xef\xbb\xbf')
    text=raw.decode('utf-8-sig')
    newline='\r\n' if '\r\n' in text else '\n'
    lines=text.splitlines()
    own=lambda line:line.split(',')[0].replace('\\','/').lower()==MOUNT_PREFIX.lower()
    lines=[line for line in lines if not own(line)]
    if entry:
        if '::Mount::' not in lines or '::Del::' not in lines:
            raise ValueError('Неизвестный формат MountLang_en.txt.')
        start=lines.index('::Mount::')+1
        end=next((i for i in range(start,len(lines)) if lines[i].startswith('::')),len(lines))
        lines.insert(end,entry)
    return (b'\xef\xbb\xbf' if bom else b'')+(newline.join(lines)+newline).encode('utf-8')
