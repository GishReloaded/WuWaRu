from __future__ import annotations
import argparse
import json
import os
import queue
import sys
import threading
import traceback
from pathlib import Path
from game import Project, GAME_DEFAULT, atomic_json
from translator import Cancelled, ServiceUnavailable

def home_path():
    return Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent

def prepare_and_launch(project,limit):
    try:
        project.translate(limit)
    except ServiceUnavailable as error:
        project.log(str(error))
        project.log('Сервис недоступен. Собираю перевод из сохранённого кэша.')
    project.build(); project.install(); project.launch()

def main():
    parser=argparse.ArgumentParser(description='WuwaRu — перевод Wuthering Waves с локальным кэшем')
    parser.add_argument('command',nargs='?',choices=['gui','extract','translate','build','install','uninstall','launch','status'],default='gui')
    parser.add_argument('--limit',type=int,default=0,help='Максимум новых строк; 0 = все')
    args=parser.parse_args()
    home=home_path()
    config_path=home/'config.json'
    if not config_path.exists():
        config=json.loads((home/'config.example.json').read_text(encoding='utf-8'))
        atomic_json(config_path,config)
    config=json.loads(config_path.read_text(encoding='utf-8'))
    if args.command=='gui':
        gui(home,config)
        return
    project=Project(home,config)
    try:
        with project.lock():
            if args.command=='extract': project.extract()
            elif args.command=='translate': project.translate(args.limit)
            elif args.command=='build': project.build()
            elif args.command=='install': project.install()
            elif args.command=='uninstall': project.uninstall()
            elif args.command=='launch':
                prepare_and_launch(project,args.limit or config.get('launch_translation_limit',1000))
            elif args.command=='status':
                print((home/'output/manifest.json').read_text(encoding='utf-8') if (home/'output/manifest.json').exists() else 'Пакет ещё не собран.')
    except KeyboardInterrupt:
        print('Остановлено. Переведённые строки сохранены.')
    except Exception as error:
        print(str(error),file=sys.stderr)
        sys.exit(1)

def gui(home,config):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    root=tk.Tk()
    root.title('WuwaRu · локальный русский перевод')
    root.geometry('830x620'); root.minsize(750,570)
    root.configure(bg='#111827')
    style=ttk.Style(root); style.theme_use('clam')
    style.configure('TFrame',background='#111827')
    style.configure('TLabel',background='#111827',foreground='#e5e7eb',font=('Segoe UI',10))
    style.configure('Title.TLabel',font=('Segoe UI',22,'bold'),foreground='#fff')
    style.configure('Muted.TLabel',foreground='#94a3b8',font=('Segoe UI',9))
    style.configure('TButton',font=('Segoe UI',10),padding=(12,8))
    frame=ttk.Frame(root,padding=24); frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='WuwaRu',style='Title.TLabel').pack(anchor='w')
    ttk.Label(frame,text='Интерфейс, квесты и диалоги · онлайн-перевод · локальный кэш',style='Muted.TLabel').pack(anchor='w',pady=(0,20))
    path=tk.StringVar(value=config.get('game_path',GAME_DEFAULT))
    ttk.Label(frame,text='Папка игры').pack(anchor='w')
    row=ttk.Frame(frame); row.pack(fill='x',pady=(4,12))
    entry=ttk.Entry(row,textvariable=path); entry.pack(side='left',fill='x',expand=True)
    def choose():
        folder=filedialog.askdirectory(initialdir=path.get())
        if folder: path.set(folder)
    browse=ttk.Button(row,text='Обзор',command=choose); browse.pack(side='left',padx=(8,0))
    row=ttk.Frame(frame); row.pack(fill='x',pady=(0,12))
    ttk.Label(row,text='Переводчик').pack(side='left')
    provider=tk.StringVar(value='Бесплатный Google' if config.get('provider')=='google_free' else 'API из config.json')
    combo=ttk.Combobox(row,textvariable=provider,values=['Бесплатный Google','API из config.json'],state='readonly',width=27)
    combo.pack(side='left',padx=10)
    ttk.Label(row,text='Новых строк при запуске').pack(side='left',padx=(12,4))
    budget=tk.StringVar(value=str(config.get('launch_translation_limit',1000)))
    spin=ttk.Spinbox(row,from_=1,to=1000000,textvariable=budget,width=8); spin.pack(side='left')
    ttk.Label(frame,text='В игре выбери English. Непереведённые строки останутся на английском.',style='Muted.TLabel').pack(anchor='w')
    ttk.Label(frame,text='Первый полный перевод большой базы может занять часы. «Остановить» сохраняет кэш.',style='Muted.TLabel').pack(anchor='w',pady=(3,12))
    status=tk.StringVar(value='Готов к работе')
    ttk.Label(frame,textvariable=status).pack(anchor='w',pady=(3,6))
    progress=ttk.Progressbar(frame,mode='indeterminate'); progress.pack(fill='x',pady=(0,12))
    events=queue.Queue(); cancelled=threading.Event(); busy=False
    text=tk.Text(frame,height=12,bg='#0b1220',fg='#cbd5e1',insertbackground='white',font=('Consolas',9),relief='flat',wrap='word',padx=10,pady=8,state='disabled')
    text.pack(fill='both',expand=True,pady=(0,14))
    buttons=[]
    actions=ttk.Frame(frame); actions.pack(fill='x')
    def log(message): events.put(('log',message))
    def start(action):
        nonlocal busy
        if busy: return
        try:
            count=int(budget.get())
            if count<1: raise ValueError()
        except ValueError:
            messagebox.showerror('Настройки','Укажи положительное количество строк.'); return
        config.update(game_path=path.get(),provider='google_free' if provider.get()=='Бесплатный Google' else 'compatible_api',launch_translation_limit=count)
        atomic_json(home/'config.json',config)
        busy=True; cancelled.clear()
        for button in buttons: button.configure(state='disabled')
        browse.configure(state='disabled'); entry.configure(state='disabled'); combo.configure(state='disabled'); spin.configure(state='disabled')
        stop.configure(state='normal'); progress.start(12)
        status.set('Выполняю…')
        def work():
            project=Project(home,dict(config),log,cancelled)
            try:
                with project.lock():
                    if action=='launch':
                        prepare_and_launch(project,count)
                    elif action=='all':
                        project.translate(); project.build()
                        log('Перевод собран. Для подключения нажми «Установить пакет».')
                    elif action=='build': project.build()
                    elif action=='install': project.install()
                    elif action=='uninstall': project.uninstall()
                events.put(('done','Готово'))
            except Cancelled as error:
                log(str(error)); events.put(('done','Остановлено; кэш сохранён'))
            except Exception as error:
                error_log=home/'data/error.log'; error_log.parent.mkdir(exist_ok=True)
                error_log.write_text(traceback.format_exc(),encoding='utf-8')
                log(str(error)); events.put(('done','Ошибка; см. журнал'))
        threading.Thread(target=work,daemon=True).start()
    def button(label,action):
        b=ttk.Button(actions,text=label,command=lambda:start(action)); b.pack(side='left',padx=(0,8)); buttons.append(b)
    button('Перевести и запустить','launch')
    button('Перевести всю базу','all')
    stop=ttk.Button(actions,text='Остановить',command=cancelled.set,state='disabled'); stop.pack(side='right')
    extra=ttk.Frame(frame); extra.pack(fill='x',pady=(10,0))
    for label,action in [('Собрать из кэша','build'),('Установить пакет','install'),('Отключить перевод','uninstall')]:
        b=ttk.Button(extra,text=label,command=lambda a=action:start(a)); b.pack(side='left',padx=(0,8)); buttons.append(b)
    def poll():
        nonlocal busy
        while not events.empty():
            kind,message=events.get()
            if kind=='log':
                text.configure(state='normal'); text.insert('end',message+'\n'); text.see('end'); text.configure(state='disabled')
                status.set(message if len(message)<110 else message[:107]+'…')
            else:
                busy=False; progress.stop(); status.set(message)
                for b in buttons: b.configure(state='normal')
                browse.configure(state='normal'); entry.configure(state='normal'); combo.configure(state='readonly'); spin.configure(state='normal'); stop.configure(state='disabled')
        root.after(150,poll)
    def close():
        if busy:
            cancelled.set(); status.set('Останавливаю и сохраняю кэш…')
            root.after(200, lambda: close() if busy else root.destroy())
        else: root.destroy()
    root.protocol('WM_DELETE_WINDOW',close)
    manifest=home/'output/manifest.json'
    if manifest.exists():
        state=json.loads(manifest.read_text(encoding='utf-8'))
        log(f'Готовый пакет: {state["translated_rows"]:,}/{state["rows"]:,} строк; осталось уникальных: {state["pending_unique_strings"]:,}.')
    poll(); root.mainloop()

if __name__=='__main__':
    main()
