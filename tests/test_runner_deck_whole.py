"""The slide deck from the handoff to an approved deck, with the two modules' own stand-ins
behind the engine and behind every worker's tools.

`slides.stand_in()` and `brand.stand_in()` keep the rules of the real slides tool and of a
real brand skill: an outline is checked as the tool checks one, a section is compiled, a
preview is rendered to real pictures, and the audit reads the deck that was rendered. The
scripted workers here use their tools as a worker does: they read their inputs, check
before they preview, look at what they are shown and hand in what they last previewed.
Nothing starts an agent, the slides tool, a brand skill or Google.
"""
import json
from pathlib import Path

import helpers  # noqa: F401
from runner_support import BLUEPRINT, OUTLINE
from test_runner_deck import MAJOR, SMALL, DeckCase

import workspace
from runner import brand as brand_skill
from runner import deck, pipeline, worker_tools
from runner import slides as slides_tool

CHOSEN = {'brand': brand_skill.BRAND, 'variant': 'light'}
# The slides tool starts a new section of work at each section slide, so this deck is drawn
# by two composers. Without the section slide it is one composer's.
PARTED = {**OUTLINE, 'slides': [
    *OUTLINE['slides'][:3],
    {'id': 'part-two', 'kind': 'section', 'title': 'What a customer will say',
     'notes': '1 min. Turn to the objection.'},
    *OUTLINE['slides'][3:]]}


class Composers:
    """What each worker of a deck does here, with the tools it is given. `asked` notes
    what each composer read and searched for."""

    def __init__(self, test):
        self.test, self.read, self.icons = test, {}, []

    def said(self, ident: str) -> dict:
        outline = self.test.workers.outline_said
        return next(slide for slide in outline['slides'] if slide['id'] == ident)

    def section(self, tools, job):
        test, spec = self.test, tools.job['artifacts']['section']
        listed = test.ok(tools.list_inputs())
        self.read[spec['prefix']] = {
            entry['name']: test.ok(tools.read_input(entry['name']))
            for entry in tools.job['inputs']}
        for name in self.read[spec['prefix']]:
            test.assertIn(name, listed)
        self.icons.append(test.ok(tools.search_icons('database')))
        made = {'version': 1, 'title': spec['title'], 'direction': spec['direction'],
                'slides': [slides_tool.sketch(self.said(slide['id']), spec['prefix'])
                           for slide in spec['slides']]}
        if tools.job['look']:   # drawn again after a review: it looks, then draws otherwise
            for slide in tools.job['look']:
                test.ok(tools.look_at_slide(slide['number']))
            made['slides'][0]['brief']['rhythm'] = 'breathing'
        text = json.dumps(made)
        checked = test.ok(tools.check_section(text))
        test.assertTrue(checked.startswith('Nothing to put right'), checked)
        shown = tools.preview_section(text)
        test.ok(shown)
        test.assertEqual(len(shown.pictures), len(spec['slides']))
        for picture in shown.pictures:
            test.assertEqual(Path(picture).read_bytes()[:8], worker_tools.PNG)
        test.ok(tools.submit_section(text, 'Nothing: it read well at once.',
                                     'The second slide is the weaker.'))


class WholeCase(DeckCase):
    """A computer whose slides tool and brand skill are the modules' own stand-ins."""

    def setUp(self):
        super().setUp()
        self.slides, self.brand = self.stand_ins()
        self.tool, self.skill = self.slides.run, self.brand.run
        self.composers = Composers(self)
        self.workers.section = self.composers.section
        self.workers.outline_said = PARTED
        self.engine.deck_needs(fresh=True)

    def ok(self, outcome) -> str:
        self.assertTrue(outcome[0], outcome[1])
        return outcome[1]

    def begin(self, **changes) -> Path:
        return self.start(**{'deck_target': 'pptx', 'brand': CHOSEN, **changes})

    def asked(self, name: str) -> list[list[str]]:
        """Every call of one command the slides stand-in was given."""
        return [call for call in self.tool.calls if ' '.join(call[:2]) == name]


class WholeDeckTests(WholeCase):
    def test_a_deck_goes_from_the_handoff_to_approved_as_powerpoint(self):
        root = self.begin()
        view = self.to_outline(root)
        self.assertEqual([slide['kind'] for slide in view['outline']['slides']], [
            'cover', 'content', 'content', 'section', 'content', 'content', 'closing'])
        self.assertTrue(self.asked('outline check'), 'the tool itself checked the outline')
        view = self.engine.outline(root, None, 'approve', seen=view['outline']['sha256'])
        self.assertEqual((view['state'], workspace.status(root)['gate']), ('waiting', 'deck'),
                         view.get('problem'))
        self.assertEqual(sorted(self.kinds()[-3:]), ['review', 'section', 'section'])
        saved, last = (root / 'deck.pptx').read_bytes(), self.built(root)['rounds'][-1]
        self.assertEqual(saved[:4], workspace.PPTX_SIGNATURE)
        self.assertEqual(saved, (root / 'work' / 'deck' / last['file']).read_bytes(),
                         'the deck that is saved is the deck that was previewed')
        self.assertEqual(workspace.sha256_file(root / 'deck.pptx'), last['deck'])
        self.assertEqual(self.asked('compose render'), [],
                         'a fresh render would be another file than the one reviewed')
        self.assertEqual(len(self.asked('compose critique')), 1)
        self.assertEqual(len(self.tool.files), 1, 'one preview file in Drive for the deck')
        shown = self.gate(root)
        self.assertEqual([(slide['number'], slide['id']) for slide in shown['slides']],
                         list(enumerate((slide['id'] for slide in PARTED['slides']), 1)))
        self.assertEqual(shown['review'], {'round': 1, 'findings': []})
        self.assertEqual(shown['audit']['status'], 'warnings')
        self.assertTrue(all(warning['code'] and warning['count'] and warning['says']
                            for warning in shown['audit']['warnings']), shown['audit'])
        objectives = list(pipeline.checks.parse_blueprint(BLUEPRINT)['objectives'])
        self.assertEqual([(row['objective'], row['cited']) for row in shown['coverage']],
                         [('O1', [2, 6]), ('O2', [3, 6]), ('O3', [5, 6])],
                         "the tool's own mark on a lead slide is no objective")
        self.assertEqual([row['objective'] for row in shown['coverage']], objectives)
        for number in range(1, 8):
            self.assertEqual(self.engine.picture(root, number, artifact='deck')[:8],
                             worker_tools.PNG)
        self.assertEqual(self.to_end(root), ['deck', 'scenario:main'])
        view = self.view(root)
        self.assertEqual((view['state'], view['finished']['ready'], view['outline'],
                          view['deck']), ('done', True, None, None))
        self.assertEqual(workspace.status(root)['artifacts']['deck'], 'approved')

    def test_a_deck_for_google_slides_is_the_previewed_deck_imported(self):
        self.workers.outline_said = OUTLINE     # one section, so one composer
        root = self.begin(deck_target='google')
        view = self.drawn(root)
        self.assertEqual((view['state'], workspace.status(root)['gate']), ('waiting', 'deck'),
                         view.get('problem'))
        last = self.built(root)['rounds'][-1]
        sent = self.asked('drive import')
        self.assertEqual(len(sent), 1)
        self.assertEqual(Path(sent[0][sent[0].index('--file') + 1]).resolve(),
                         (root / 'work' / 'deck' / last['file']).resolve())
        link = (root / 'deck-link.md').read_text()
        made = [file for file in self.tool.files.values()
                if not file['name'].startswith('Preview: ')]
        self.assertEqual(len(made), 1, self.tool.files)
        self.assertIn(f"with the SHA-256 {last['deck']}", link)
        self.assertRegex(link, r'- URL: https://\S+\n- Title: Rolling restarts\n- ID: \S+\n')
        self.assertFalse((root / 'deck.pptx').exists())
        self.assertEqual(len(self.gate(root)['slides']), 6)
        self.assertEqual(self.kinds().count('section'), 1)
        self.assertEqual(self.to_end(root), ['deck', 'scenario:main'])
        self.assertEqual([entry['name'] for entry in self.engine.previews_left()],
                         ['Preview: Rolling restarts'])

    def test_a_major_finding_about_drawing_has_its_section_drawn_again(self):
        self.workers.found = [[MAJOR, SMALL]]
        root = self.begin()
        view = self.drawn(root)
        self.assertEqual((view['state'], workspace.status(root)['gate']), ('waiting', 'deck'),
                         view.get('problem'))
        self.assertEqual(self.kinds()[-6:], ['outline', 'section', 'section', 'review',
                                             'section', 'review'])
        spec = [spec for kind, _, spec in self.workers.jobs if kind == 'section'][-1]
        self.assertEqual(spec['artifacts']['section']['prefix'], 's1_')
        self.assertEqual([slide['number'] for slide in spec['look']], [2, 3])
        self.assertEqual(len(self.asked('compose critique')), 2,
                         'each render takes its own assessment')
        self.assertEqual(len(self.tool.files), 1, 'and the deck still has one preview file')
        self.assertEqual(self.gate(root)['review'], {'round': 2, 'findings': []})
        self.assertEqual(self.to_end(root), ['deck', 'scenario:main'])

    def test_with_levels_and_previews_on_this_computer_nothing_goes_to_drive(self):
        self.tool.local = True
        self.set_previews('local')
        root = self.begin(levels=['101', '201'])
        self.to_outline(root, '101')
        view = self.engine.outline(root, '101', 'approve')
        self.assertEqual((workspace.status(root)['gate'], view['deck']['level']),
                         ('deck@101', '101'), view.get('problem'))
        self.assertEqual(self.tool.files, {})
        self.assertEqual(self.engine.previews_left(), [])
        self.assertTrue((root / '101' / 'deck.pptx').is_file())

    def set_previews(self, how: str) -> None:
        from dataclasses import replace
        from runner import settings
        settings.save(replace(settings.load(), previews=how))
        self.engine.deck_needs(fresh=True)


class TroubleTests(WholeCase):
    def test_what_a_deck_needs_is_read_from_what_the_two_modules_say(self):
        needs = self.engine.deck_needs(fresh=True)
        self.assertEqual((needs['missing'], needs['how'], needs['drive'], needs['local']),
                         ([], 'drive', True, True))
        self.assertEqual(needs['brand'], {
            'found': True, 'name': self.brand.name, 'problem': None,
            'brands': [{'brand': 'example', 'name': 'Example Co',
                        'variants': ['light', 'dark']}]})
        self.assertEqual([(item['id'], item['state']) for item in needs['items']], [
            ('deck-slides', 'ok'), ('deck-brand', 'ok'), ('deck-previews', 'ok'),
            ('deck-pictures', 'ok')])
        self.assertEqual(needs['items'][0]['facts'][0]['detail'], slides_tool.MINIMUM)
        self.tool.drive = False
        needs = self.engine.deck_needs(fresh=True)
        self.assertEqual((needs['missing'], needs['drive']), ([self.engines.NO_DRIVE], False))
        self.tool.local = False
        needs = self.engine.deck_needs(fresh=True)
        self.assertEqual((needs['local'], needs['how']), (False, 'drive'))
        self.assertEqual(needs['items'][2]['state'], 'problem')
        self.assertEqual(self.engine.brand_skills(), [
            {'name': self.brand.name, 'path': str(self.brand.runtime), 'chosen': True}])

    def test_a_brand_that_changed_underneath_stops_the_deck_and_says_so(self):
        root = self.begin()
        self.to_outline(root)
        tokens = self.skill.home / 'brand' / 'tokens.json'
        tokens.write_text(tokens.read_text() + '\n')
        view = self.engine.outline(root, None, 'approve')
        self.assertEqual(view['state'], 'stopped')
        self.assertIn('The brand changed underneath this deck after it was exported. The '
                      'brand skill refused:', view['problem']['what'])
        self.assertEqual(self.kinds().count('section'), 0)
        view = self.engine.act(root, 'retry')
        self.assertEqual((view['state'], workspace.status(root)['gate']), ('waiting', 'deck'),
                         view.get('problem'))

    def test_a_preview_that_fails_after_its_upload_is_still_listed_as_left_in_drive(self):
        root = self.begin()
        self.to_outline(root)
        # As the tool fails when its upload worked and its render did not: the file is there.
        self.tool.files['file-9'] = {'name': 'Preview: Rolling restarts', 'uploads': 1}
        self.tool.fails['compose preview'] = (
            'The render has 8 pages for 2 slides; check the deck for an import problem The '
            'preview deck is in Drive (https://docs.example.com/presentation/d/file-9/edit); '
            'retry with --file-id file-9.')
        tried = []

        def composer(tools, job):
            spec = tools.job['artifacts']['section']
            made = json.dumps({
                'version': 1, 'title': spec['title'], 'direction': spec['direction'],
                'slides': [slides_tool.sketch(self.composers.said(slide['id']),
                                              spec['prefix']) for slide in spec['slides']]})
            tried.append(tools.preview_section(made))
            del self.tool.fails['compose preview']
            self.ok(tools.preview_section(made))
            self.ok(tools.submit_section(made))

        self.engine = self.make(at_once=1)
        self.workers.then('section', composer)
        view = self.engine.outline(root, None, 'approve')
        self.assertEqual((view['state'], workspace.status(root)['gate']), ('waiting', 'deck'),
                         view.get('problem'))
        self.assertFalse(tried[0][0])
        self.assertIn('could not be rendered, and this did not use up a preview', tried[0][1])
        self.assertNotIn(str(self.base), tried[0][1])
        sent = [call[call.index('--file-id') + 1] for call in self.asked('compose preview')
                if '--file-id' in call]
        self.assertEqual(set(sent), {'file-9'}, 'every later preview writes that file again')
        self.assertEqual(len(sent), len(self.asked('compose preview')) - 1)
        self.assertEqual(self.engine.previews_left(), [{
            'name': 'Preview: Rolling restarts', 'training': 'Rolling restarts',
            'url': 'https://docs.example.com/presentation/d/file-9/edit'}])


class GivenTests(WholeCase):
    def test_a_composer_reads_the_tools_guidance_and_an_example_of_each_relation_it_draws(self):
        self.engine = self.make(at_once=1)
        root = self.begin()
        self.drawn(root)
        first, second = self.composers.read['s1_'], self.composers.read['s2_']
        fixed = ['brief', 'composition contract', 'design guidance', 'composition guidance',
                 'gallery']
        self.assertEqual(list(first), [*fixed, 'example contrast', 'example order'])
        self.assertEqual(list(second), [*fixed, 'example contrast', 'example order'])
        self.assertIn('submit_section', first['brief'])
        self.assertNotIn(str(self.base), ''.join(first.values()))
        told = self.slides.reading(self.base / 'nowhere.json')
        self.assertEqual(first['design guidance'].strip(), told['design guidance'].strip())
        writer = [spec for kind, _, spec in self.workers.jobs if kind == 'outline'][-1]
        self.assertEqual([entry['name'] for entry in writer['inputs']], [
            'handoff', 'outline contract', 'drafting guidance', 'blueprint', 'learner guide',
            'research findings', 'naming rules'])
        reviewer = [spec for kind, _, spec in self.workers.jobs if kind == 'review'][-1]
        self.assertEqual([entry['name'] for entry in reviewer['inputs']], ['the review'])

    def test_a_composer_is_offered_only_the_icons_the_slides_tool_can_place(self):
        root = self.begin()
        self.drawn(root)
        found = self.composers.icons[-1]
        self.assertIn('- ex-database: Icon database', found)
        self.assertEqual(self.ok(self.picture_search('photo')).count('\n- '), 0)

    def picture_search(self, words: str):
        folder = self.base / 'one-job'
        whole = deck.complete(OUTLINE, self.slides.layouts(self.contract())['layouts'], [])
        worker_tools.prepare(folder, artifacts={'section': {
            'kind': 'section', 'brand': str(self.contract()),
            **deck.fixed(whole, ['what-it-does'], 1)}})
        return worker_tools.WorkerTools(folder, slides=self.slides,
                                        brand=self.brand).search_icons(words)

    def contract(self) -> Path:
        folder = self.base / 'exported'
        if not folder.exists():
            self.brand.export(folder, brand_skill.BRAND, 'light')
        return folder / 'brand-contract.json'

    def test_the_engine_and_a_workers_tools_use_the_same_tool_and_the_same_brand_skill(self):
        root = self.begin()
        self.drawn(root)
        for kind, _, spec in self.workers.jobs:
            if kind in ('outline', 'section', 'review'):
                self.assertEqual(spec['runtimes'], {'slides': str(self.slides.runtime),
                                                    'brand': str(self.brand.runtime)}, kind)
            else:
                self.assertEqual(spec['runtimes'], {}, kind)


if __name__ == '__main__':
    import unittest
    unittest.main()
