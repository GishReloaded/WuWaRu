"""Online translation with a durable cache; no game-process access."""
from __future__ import annotations
import collections
import hashlib
import json
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TOKEN = re.compile(r'<[^<>\n]+>|\{[^{}\n]*\}|(?<!\d)%(?:\d+\$)?(?:[-+0#]*\d*(?:\.\d+)?[sdfiu]|[-+0 #]*\d*(?:\.\d+)?[sdfiu](?![A-Za-z]))|\\[nr]|\r\n|\n|\[[^\[\]\n]*(?:Gender|gender|Player|player|Rover|Key|key)[^\[\]\n]*\]')
LEGACY_PERCENT = re.compile(r'%(?:\d+\$)?[-+0 #]*\d*(?:\.\d+)?[sdfiu]')
MARKER = re.compile(r'⟪\s*(\d{6})\s*⟫')
PROTECTED = re.compile(r'⟦\s*P\s*(\d{5})\s*⟧', re.I)
CHOICE = re.compile(r'\{Male=(?P<male>[^{};]*);Female=(?P<female>[^{}]*)\}|\{Cus:Ipt,Touch=(?P<touch>[^{}]*?) PC=(?P<pc>[^{}]*?) Gamepad=(?P<pad>[^{}]*)\}|\{Cus:Sap,S=(?P<single>[^{}]*?) P=(?P<plural>[^{}]*?) SapTag=(?P<tag>[0-9A-Za-z]+)\}')
FRAGMENT_LITERALS={'The':'','the':'','A':'','a':'','An':'','an':'','I':'Я'}

def choice_values(text):
    return [value for match in CHOICE.finditer(text)
            for name,value in match.groupdict().items() if name!='tag' and value is not None]

def localize_choices(text, choices):
    def replace(match):
        result=match.group(); spans=[]
        for name,value in match.groupdict().items():
            if name=='tag' or value is None or value not in choices: continue
            translated=choices[value]
            if any(c in translated for c in '{};=\r\n'):
                raise ValueError('Недопустимая структура перевода варианта текста.')
            start,end=match.span(name)
            spans.append((start-match.start(),end-match.start(),translated))
        for start,end,translated in sorted(spans,reverse=True):
            result=result[:start]+translated+result[end:]
        return result
    return CHOICE.sub(replace,text)

def format_signature(text):
    # Literal selector branches are text. Keys, selectors, numeric references,
    # tags and ordinary variables must remain identical.
    def normalize(match):
        result=match.group(); spans=[]
        for name,value in match.groupdict().items():
            if name!='tag' and value is not None:
                start,end=match.span(name); spans.append((start-match.start(),end-match.start()))
        for start,end in sorted(spans,reverse=True): result=result[:start]+'TEXT'+result[end:]
        return result
    return TOKEN.findall(CHOICE.sub(normalize,text))

class Cancelled(Exception):
    pass

class ServiceUnavailable(RuntimeError):
    pass

def check_cancel(event):
    if event.is_set():
        raise Cancelled('Перевод остановлен. Кэш сохранён.')

def protect(text: str):
    parts = []
    def sub(match):
        parts.append(match.group())
        return f'⟦P{len(parts)-1:05}⟧'
    return TOKEN.sub(sub, text), parts

def restore(text: str, parts: list[str]):
    # Every placeholder must occur once, in original order. Never cache broken text.
    found = [int(m.group(1)) for m in PROTECTED.finditer(text)]
    if found != list(range(len(parts))):
        raise ValueError('Переводчик изменил переменные или теги. Строка оставлена на английском.')
    # Original line breaks are protected parts. Any literal line break here
    # was introduced by the service (for example, wrapping a long paragraph).
    text=re.sub(r'\r\n|\n',' ',text)
    return PROTECTED.sub(lambda m: parts[int(m.group(1))], text)

def needs_unmarked_retry(source, russian):
    bare = TOKEN.sub('', source).strip()
    result = TOKEN.sub('', russian)
    # Keep acronyms and internal identifiers. Ordinary names/phrases may need
    # an individual request because Google sometimes ignores a marked row.
    return (translatable(source) and not re.search(r'[А-Яа-яЁё]', result)
            and bool(re.search(r'[a-z]', bare)) and '_' not in bare
            and not re.search(r'https?://', bare))

def latin_sentence_fragments(text):
    # Find prose still in English, including partial translations of long rows.
    bare=TOKEN.sub(' ',text)
    runs=re.findall(r"\b[A-Za-z][A-Za-z'-]*(?:[ ,:]+[A-Za-z][A-Za-z'-]*){4,}\b",bare)
    return [run for run in runs if re.search(r'\b(?:I|you|we|he|she|the|and|to|of|with|is|are|will|that|for|in)\b',run,re.I)]

def needs_mixed_retry(russian):
    return bool(re.search(r'[А-Яа-яЁё]',russian) and latin_sentence_fragments(russian))

def needs_percent_repair(source):
    # Earlier versions treated the beginning of "18% for" as a printf token.
    for match in LEGACY_PERCENT.finditer(source):
        if match.start() and source[match.start()-1].isdigit(): return True
        if (' ' in match.group() and match.end()<len(source)
                and source[match.end()].isascii() and source[match.end()].isalpha()): return True
    return False

def localize_terms(text, terms):
    if not terms: return text
    pattern = re.compile(r'(?<!\w)(?:'+ '|'.join(re.escape(s) for s in sorted(terms,key=len,reverse=True)) +r')(?!\w)')
    def fragment(value): return pattern.sub(lambda match: terms[match.group()],value)
    result=[]; offset=0
    for match in TOKEN.finditer(text):
        result.extend((fragment(text[offset:match.start()]),match.group()))
        offset=match.end()
    result.append(fragment(text[offset:]))
    return ''.join(result)

class Cache:
    def __init__(self, path: Path):
        self.con = sqlite3.connect(path)
        self.con.execute('pragma journal_mode=WAL')
        self.con.execute('create table if not exists translations (key text primary key, source text not null, russian text not null, provider text not null, created integer not null)')
    @staticmethod
    def key(source):
        return hashlib.sha256(('en\0ru\0'+source).encode()).hexdigest()
    def all(self):
        return dict(self.con.execute('select source, russian from translations'))
    def put(self, source, russian, provider):
        self.con.execute('insert or replace into translations values (?,?,?,?,?)', (self.key(source), source, russian, provider, int(time.time())))
    def commit(self):
        self.con.commit()
    def close(self):
        self.con.commit()
        self.con.close()

class Provider:
    def __init__(self, config, cancelled: threading.Event):
        self.config = config
        self.cancelled = cancelled
        self.name = config.get('provider', 'google_free')
        self.last_call = 0.0
    def request(self, url, data=None, headers=None):
        for attempt in range(5):
            check_cancel(self.cancelled)
            delay = float(self.config.get('request_delay', 0.7)) - (time.monotonic()-self.last_call)
            if delay > 0 and self.cancelled.wait(delay):
                check_cancel(self.cancelled)
            try:
                req = urllib.request.Request(url, data=data, headers={'User-Agent':'Mozilla/5.0 WuwaRu/0.1', **(headers or {})})
                self.last_call = time.monotonic()
                with urllib.request.urlopen(req, timeout=20 if self.name=='google_free' else 45) as response:
                    return json.load(response)
            except (urllib.error.URLError, TimeoutError) as exc:
                if isinstance(exc, urllib.error.HTTPError) and exc.code not in (408,429,500,502,503,504):
                    raise ServiceUnavailable(f'Сервис перевода: HTTP {exc.code}. Проверь настройки.') from exc
                if attempt == 4:
                    raise ServiceUnavailable('Сервис перевода недоступен или ограничил запросы. Кэш сохранён; повтори позже.') from exc
                if self.cancelled.wait(min(60, 2**attempt * 3)):
                    check_cancel(self.cancelled)
    def free_text(self, text):
        if len(text)>4200:
            boundary=max(text.rfind('. ',1500,4000),text.rfind(' ',1500,4000),text.rfind('\n',1500,4000))
            if boundary<0:
                raise ValueError('Слишком длинная строка без границ слов.')
            return self.free_text(text[:boundary+1])+' '+self.free_text(text[boundary+1:])
        query = urllib.parse.urlencode({'client':'gtx','sl':'en','tl':'ru','dt':'t','q':text})
        result = self.request('https://translate.googleapis.com/translate_a/single?'+query)
        if not result or not isinstance(result[0],list):
            raise ValueError('Неожиданный ответ бесплатного переводчика')
        return ''.join(item[0] for item in result[0] if item and isinstance(item[0],str))
    def translate(self, sources: list[str]):
        prepared = [protect(s) for s in sources]
        if self.name == 'compatible_api':
            key = os.environ.get(self.config.get('api_key_env', 'WUWA_TRANSLATE_API_KEY'), '')
            if not key:
                raise RuntimeError('API-ключ не задан в переменной WUWA_TRANSLATE_API_KEY.')
            endpoint = self.config.get('api_base', '').rstrip('/')
            if not endpoint.startswith('https://') and not endpoint.startswith('http://127.0.0.1'):
                raise ValueError('В настройках API требуется HTTPS URL.')
            body = {'model':self.config.get('api_model',''), 'temperature':0,
                    'messages':[{'role':'system','content':'Translate Wuthering Waves game strings from English to Russian. Use consistent terminology, fluent Russian, preserve all ⟦P00000⟧ placeholders in their original order. Return ONLY a JSON array of translated strings, exactly matching the input count and order.'},
                                {'role':'user','content':json.dumps([s for s,_ in prepared],ensure_ascii=False)}]}
            result = self.request(endpoint+'/chat/completions', json.dumps(body).encode(), {'Content-Type':'application/json','Authorization':'Bearer '+key})
            answer = result['choices'][0]['message']['content'].strip()
            if answer.startswith('```'):
                answer = re.sub(r'^```(?:json)?\s*|\s*```$', '', answer)
            output = json.loads(answer)
            if not isinstance(output,list) or len(output)!=len(sources) or not all(isinstance(s,str) for s in output):
                raise ValueError('API вернул неправильное количество строк.')
        else:
            # A marker separates whole rows, including rows containing real newlines.
            combined = '\n\n'.join(f'⟪{i:06}⟫\n{text}' for i,(text,_) in enumerate(prepared))
            translated = self.free_text(combined)
            matches = list(MARKER.finditer(translated))
            if [int(m.group(1)) for m in matches] != list(range(len(sources))):
                if len(sources)>1:
                    middle=len(sources)//2
                    return self.translate(sources[:middle])+self.translate(sources[middle:])
                output=[self.free_text(prepared[0][0])]
            else:
                output=[translated[m.end():matches[i+1].start() if i+1<len(matches) else len(translated)].strip() for i,m in enumerate(matches)]
        restored = []
        for source, result, (_, parts) in zip(sources, output, prepared):
            if not result.strip() and source.strip():
                raise ValueError('Переводчик вернул пустую строку.')
            russian = restore(result,parts)
            if self.name == 'google_free' and (needs_unmarked_retry(source, russian) or needs_mixed_retry(russian)):
                # Send just this row, without the batch row marker. Protect and
                # validate formatting exactly as in the normal translation path.
                russian = restore(self.free_text(prepared[len(restored)][0]), parts)
                if not russian.strip(): raise ValueError('Пустой индивидуальный перевод.')
            restored.append(russian)
        return restored
    def translate_fragmented(self, source):
        # Retry a damaged row without ever sending its control tokens online.
        # This loses some sentence context, but preserves all game formatting.
        pieces=[]; offset=0
        for match in TOKEN.finditer(source):
            pieces.extend(((False,source[offset:match.start()]),(True,match.group())))
            offset=match.end()
        pieces.append((False,source[offset:]))
        pending=list(dict.fromkeys(text.strip() for control,text in pieces
                                   if not control and translatable(text) and text.strip() not in FRAGMENT_LITERALS))
        translated=dict(FRAGMENT_LITERALS)
        # Dense skill descriptions may contain dozens of tags. Translate the
        # human fragments together instead of making one request per tag gap.
        for batch in batches(pending): translated.update(zip(batch,self.translate(batch)))
        result=[]
        for control,text in pieces:
            if control or (not translatable(text) and text.strip() not in FRAGMENT_LITERALS): result.append(text); continue
            leading=text[:len(text)-len(text.lstrip())]
            trailing=text[len(text.rstrip()):]
            result.append(leading+translated[text.strip()]+trailing)
        output=''.join(result)
        if TOKEN.findall(output)!=TOKEN.findall(source):
            raise ValueError('Не удалось сохранить разметку строки.')
        return output

def batches(sources, max_chars=3000, max_rows=35):
    batch=[]; size=0
    for source in sources:
        length=len(protect(source)[0])+20
        if batch and (size+length>max_chars or len(batch)>=max_rows):
            yield batch; batch=[]; size=0
        batch.append(source); size+=length
    if batch:
        yield batch

def translatable(source):
    # Skip pure numbers, URLs and internal names with no human-readable text.
    bare = TOKEN.sub('', source).strip()
    return bool(re.search(r'[A-Za-z]{2}',bare)) and not re.fullmatch(r'https?://\S+',bare)

def translate_pending(sources, cache, config, cancelled, log, limit=0):
    known=cache.all()
    pending=[s for s in sources if s not in known and translatable(s)]
    total=len(pending)
    if limit:
        pending=pending[:limit]
    log(f'Уникальных строк: {len(sources):,}. В кэше: {sum(s in known for s in sources):,}. Ожидают перевода: {total:,}.')
    provider=Provider(config,cancelled)
    done=0; failed=0
    def process(batch):
        nonlocal done,failed
        check_cancel(cancelled)
        try:
            output=provider.translate(batch)
        except (ValueError, KeyError, json.JSONDecodeError):
            if len(batch)>1:
                mid=len(batch)//2; process(batch[:mid]); process(batch[mid:]); return
            try:
                if not TOKEN.search(batch[0]): raise ValueError()
                output=[provider.translate_fragmented(batch[0])]
            except (ValueError, KeyError, json.JSONDecodeError):
                failed+=1
                log('Пропущена строка с изменёнными тегами: '+batch[0][:70])
                return
        for source,russian in zip(batch,output):
            cache.put(source,russian,provider.name)
        cache.commit()
        done+=len(batch)
    for batch in batches(pending):
        process(batch)
        log(f'Переведено {done:,}/{len(pending):,}; ошибок разметки: {failed}.')
    return done,failed
