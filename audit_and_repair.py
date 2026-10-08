"""Retry untranslated marked rows and write a local translation audit."""
from pathlib import Path
import json
import re
import threading
from game import Project, atomic_json
from translator import Cache, Provider, TOKEN, needs_unmarked_retry, needs_percent_repair, needs_mixed_retry, latin_sentence_fragments, protect, restore, translatable, choice_values, batches

def main():
    home=Path(__file__).resolve().parent
    config=json.loads((home/'config.json').read_text(encoding='utf-8'))
    project=Project(home,config)
    with project.lock():
        cache=Cache(home/'data/cache.sqlite3')
        try:
            known=cache.all()
            # Numbered names are labels, rather than the English answer "No".
            for source in known:
                if re.fullmatch(r'"?No\. \d+"?',source):
                    project.glossary[source]=source.replace('No.','№',1)
            atomic_json(home/'glossary.json',project.glossary)
            candidates=[s for s,r in known.items() if s not in project.glossary and (needs_unmarked_retry(s,r) or needs_percent_repair(s) or needs_mixed_retry(r) or TOKEN.findall(s)!=TOKEN.findall(r))]
            individual=[s for s in candidates if needs_unmarked_retry(s,known[s]) or needs_mixed_retry(known[s]) or TOKEN.findall(s)!=TOKEN.findall(known[s])]
            percentages=[s for s in candidates if s not in set(individual)]
            provider=Provider(dict(config,provider='google_free'),threading.Event())
            repaired=reviewed=0
            def save(source,russian):
                nonlocal repaired,reviewed
                if not russian.strip(): raise ValueError('Empty individual translation')
                if TOKEN.findall(source)!=TOKEN.findall(russian): raise ValueError('Control tokens changed')
                if russian != known[source]:
                    cache.put(source,russian,'google_free_unmarked')
                    cache.commit(); known[source]=russian; repaired+=1
                reviewed+=1
                print(f'Review {reviewed}/{len(candidates)}; corrected {repaired}',flush=True)
            for source in individual:
                masked,parts=protect(source)
                try:
                    russian=restore(provider.free_text(masked),parts)
                except ValueError:
                    russian=provider.translate_fragmented(source)
                save(source,russian)
            def review_batch(batch):
                try: result=provider.translate(batch)
                except ValueError:
                    if len(batch)>1:
                        middle=len(batch)//2; review_batch(batch[:middle]); review_batch(batch[middle:]); return
                    result=[provider.translate_fragmented(batch[0])]
                for source,russian in zip(batch,result): save(source,russian)
            for batch in batches(percentages): review_batch(batch)
            missing=[s for s in project.sources() if translatable(s) and s not in known]
            unresolved=[s for s,r in known.items() if s not in project.glossary and needs_unmarked_retry(s,r)]
            paragraphs=[s for s in unresolved if len(re.findall(r'[A-Za-z]+',TOKEN.sub('',s)))>=8]
            mixed=[{'source':s,'fragments':latin_sentence_fragments(r)} for s,r in known.items()
                   if s not in project.glossary and needs_mixed_retry(r)]
            missing_choices=sorted({v for *_,s in project.rows() for v in choice_values(s) if v not in project.choices})
            report={'cached_unique_strings':len(known),'reviewed_unique_strings':len(candidates),
                    'individual_reviews':len(individual),'percent_only_reviews':len(percentages),
                    'corrected':repaired,'missing_eligible_strings':len(missing),
                    'unresolved_latin_labels':unresolved,'unresolved_sentence_candidates':paragraphs,
                    'unresolved_mixed_sentences':mixed,'missing_selector_values':missing_choices,
                    'complete_eligible_coverage':not missing and not missing_choices,
                    'scope':'Local game localization databases; acronyms, internal identifiers and proper names may retain Latin characters.'}
            atomic_json(home/'data/translation-audit.json',report)
            print(json.dumps({k:v for k,v in report.items() if not isinstance(v,list)},ensure_ascii=False),flush=True)
        finally:
            cache.close()

if __name__=='__main__': main()
