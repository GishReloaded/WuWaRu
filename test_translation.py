import json
import sqlite3
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from game import update_mount, MOUNT_PREFIX, steam_app_id
from translator import Cache, Provider, ServiceUnavailable, protect, restore, translate_pending, localize_terms, TOKEN, needs_percent_repair, localize_choices, format_signature, needs_mixed_retry
from main import prepare_and_launch
from make_portable import FILES, make_archive

class TranslationTests(unittest.TestCase):
    def test_public_archive_excludes_local_state_and_external_binaries(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder)
            for name in FILES+['config.json','data/cache.sqlite3','data/source/secret.db',
                               'output/local.pak','tools/fmodel/FModelCLI.exe','tools/pakkeys.txt']:
                path=home/name; path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text('local fixture',encoding='utf-8')
            archive=make_archive(home,home/'public.zip')
            with zipfile.ZipFile(archive) as z:
                self.assertEqual(set(z.namelist()),{'WuwaRu/'+name for name in FILES})
                self.assertIsNone(z.testzip())
    def test_clean_checkout_creates_local_config_from_template(self):
        from unittest.mock import patch
        import main
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder)
            template={'provider':'google_free','game_path':'example'}
            (home/'config.example.json').write_text(json.dumps(template),encoding='utf-8')
            for name in ('glossary.json','overrides.json'):
                (home/name).write_text('{}',encoding='utf-8')
            with patch('main.home_path',return_value=home), patch('sys.argv',['main.py','status']), patch('builtins.print'):
                main.main()
            self.assertEqual(json.loads((home/'config.json').read_text(encoding='utf-8')),template)
            saved={'provider':'compatible_api','game_path':'custom'}
            (home/'config.json').write_text(json.dumps(saved),encoding='utf-8')
            with patch('main.home_path',return_value=home), patch('sys.argv',['main.py','status']), patch('builtins.print'):
                main.main()
            self.assertEqual(json.loads((home/'config.json').read_text(encoding='utf-8')),saved)
    def test_service_line_wrapping_does_not_change_original_breaks(self):
        masked,parts=protect('Hello\nWorld')
        self.assertEqual(restore(masked.replace('Hello','Привет\nдруг'),parts),'Привет друг\nWorld')
    def test_isolated_article_may_have_no_russian_equivalent(self):
        p=Provider({},threading.Event())
        p.translate=lambda rows:[s.replace('World','Мир') for s in rows]
        source='The <b>World</b>\nI <b>World</b>'
        result=p.translate_fragmented(source)
        self.assertEqual(result,' <b>Мир</b>\nЯ <b>Мир</b>')
        self.assertEqual(TOKEN.findall(source),TOKEN.findall(result))
    def test_dense_markup_fallback_batches_and_deduplicates_fragments(self):
        p=Provider({},threading.Event()); calls=[]
        def translate(rows):
            calls.append(rows)
            return [r.replace('Hello','Привет').replace('World','Мир') for r in rows]
        p.translate=translate
        source='<b>Hello</b> {0} <i>World</i> <b>Hello</b>'
        result=p.translate_fragmented(source)
        self.assertEqual(result,'<b>Привет</b> {0} <i>Мир</i> <b>Привет</b>')
        self.assertEqual(calls,[['Hello','World']])
        self.assertEqual(TOKEN.findall(source),TOKEN.findall(result))
    def test_partial_english_sentence_is_detected(self):
        self.assertTrue(needs_mixed_retry('Привет. I will give everything to pass the remaining trials.'))
        self.assertFalse(needs_mixed_retry('Урон Spectro DMG: {PlayerName} <color=the>10%</color>'))
    def test_selector_text_can_change_without_changing_selector_keys(self):
        source='{Cus:Ipt,Touch=Tap PC=Click Gamepad=Press} {Male=he;Female=she} {Cus:Sap,S=stack P=stacks SapTag=A} {PlayerName} {Cus:Var,VarType=Global Key=main_team_name}'
        result=localize_choices(source,{'Tap':'Нажмите','Click':'Щёлкните','Press':'Нажмите','he':'он','she':'она','stack':'эффект','stacks':'эффектов','main_team_name':'нельзя'})
        self.assertIn('Touch=Нажмите PC=Щёлкните Gamepad=Нажмите',result)
        self.assertIn('Male=он;Female=она',result)
        self.assertEqual(format_signature(source),format_signature(result))
        self.assertNotEqual(format_signature(source),format_signature(result.replace('SapTag=A','SapTag=B')))
        self.assertIn('Key=main_team_name',result)
        with self.assertRaises(ValueError): localize_choices(source,{'Tap':'bad} injected {'})
    def test_percentage_prose_is_not_a_printf_placeholder(self):
        source='Increases DEF by 18% for 360s; {0}% during combat; 100% survival.'
        self.assertEqual(TOKEN.findall(source),['{0}'])
        self.assertTrue(needs_percent_repair(source))
        self.assertEqual(TOKEN.findall('Damage: %d; value %.2f; name %s; signed % d'),['%d','%.2f','%s','% d'])
    def test_terms_do_not_rewrite_markup_or_variables(self):
        text='<color=HP>DMG от Tacet Discords: {DMG} HP; XDMGY'
        result=localize_terms(text,{'DMG':'урон','HP':'ОЗ','Tacet Discords':'Безмолвные диссонансы'})
        self.assertEqual(result,'<color=HP>урон от Безмолвные диссонансы: {DMG} ОЗ; XDMGY')
    def test_unchanged_marked_row_retries_without_row_marker(self):
        p=Provider({},threading.Event())
        sent=[]
        def free(text):
            sent.append(text)
            return text if '⟪' in text else text.replace('Insufficient Echo level','Недостаточный уровень Эха')
        p.free_text=free
        self.assertEqual(p.translate(['Insufficient Echo level']),['Недостаточный уровень Эха'])
        self.assertEqual(len(sent),2)
        self.assertNotIn('⟪',sent[1])
    def test_steam_manifest_must_match_installation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'steamapps'; game=root/'common/Wuthering Waves'
            game.mkdir(parents=True)
            (root/'appmanifest_3513350.acf').write_text('"appid" "3513350"\n"installdir" "Wuthering Waves"')
            (root/'appmanifest_999.acf').write_text('"appid" "999"\n"installdir" "Another Game"')
            self.assertEqual(steam_app_id(game),'3513350')
            self.assertIsNone(steam_app_id(root/'common/Missing Game'))
    def test_service_unavailable_launches_from_cache(self):
        from unittest.mock import Mock
        project=Mock()
        project.translate.side_effect=ServiceUnavailable('offline')
        prepare_and_launch(project,1000)
        project.build.assert_called_once()
        project.install.assert_called_once()
        project.launch.assert_called_once()
    def test_markup_and_variables_roundtrip(self):
        original='<color=#fff>Hello {PlayerName}!</color>\nDamage: %d\\n'
        masked,parts=protect(original)
        self.assertEqual(restore(masked.replace('Hello','Привет').replace('Damage','Урон'),parts),original.replace('Hello','Привет').replace('Damage','Урон'))
        with self.assertRaises(ValueError): restore(masked.replace('⟦P00001⟧',''),parts)
        with self.assertRaises(ValueError): restore(masked.replace('⟦P00000⟧','⟦P00001⟧'),parts)
    def test_batch_preserves_multiline_rows(self):
        provider=Provider({},threading.Event())
        provider.free_text=lambda text:text.replace('Hello','Привет').replace('World','Мир')
        self.assertEqual(provider.translate(['Hello\nWorld','Hello {0}']),['Привет\nМир','Привет {0}'])
    def test_changed_source_does_not_hit_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            c=Cache(Path(folder)/'cache.db'); c.put('Accept','Принять','test'); c.commit(); c.close()
            c=Cache(Path(folder)/'cache.db')
            self.assertEqual(c.all()['Accept'],'Принять')
            self.assertNotIn('Accept now',c.all()); c.close()
    def test_mount_preserves_other_mods_and_delete_section(self):
        raw=b'\xef\xbb\xbf::Mount::\r\nLang_en/Base/base,4,AAA,BBB,,\r\nLang_en/RU/other,900,C,D,,\r\n::Del::\r\nobsolete,2,E,F,,\r\n'
        entry=f'{MOUNT_PREFIX},900,ABCD,,,'
        added=update_mount(raw,entry)
        self.assertEqual(update_mount(added,entry),added)
        self.assertEqual(update_mount(added,None),raw)
        self.assertEqual(added.count(MOUNT_PREFIX.encode()),1)
    def test_damaged_tokens_retry_without_sending_control_text(self):
        p=Provider({},threading.Event())
        sent=[]
        def translate(rows):
            sent.extend(rows)
            return [r.replace('Hello','Привет').replace('World','Мир') for r in rows]
        p.translate=translate
        source='Hello {PlayerName}\n<color=#fff>World</color>'
        self.assertEqual(p.translate_fragmented(source),'Привет {PlayerName}\n<color=#fff>Мир</color>')
        self.assertFalse(any('PlayerName' in s or '<color' in s for s in sent))

if __name__=='__main__': unittest.main()
