"""The slide deck from the handoff to an approved deck, with the stand-ins for the slides
tool and a brand skill behind the engine and behind every worker's tools.

The two in tests/stand_ins keep the rules of the real slides tool and of a
real brand skill: an outline is checked as the tool checks one, a section is compiled, a
preview is rendered to real pictures, and the audit reads the deck that was rendered. The
scripted workers here use their tools as a worker does: they read their inputs, check
before they preview, look at what they are shown and hand in what they last previewed.
Nothing starts an agent, the slides tool, a brand skill or Google.
"""
import json
from pathlib import Path

import helpers  # noqa: F401
import runner_support
from runner_support import BLUEPRINT, OUTLINE
from test_runner_deck import MAJOR, SMALL, DeckCase

import workspace
from runner import deck, pipeline, worker_tools
from runner import slides as slides_tool
from stand_ins import brand as brand_stand_in
from stand_ins import slides as slides_stand_in

CHOSEN = {'brand': brand_stand_in.BRAND, 'variant': 'light'}
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

    @staticmethod
    def intent(brief: str, ident: str) -> dict | None:
        """The intent a section's brief gives one slide to copy, or None when it gives none."""
        mine = brief.partition(f'### `{ident}`')[2].partition('\n#')[0]
        if '`intent`, to copy:' not in mine:
            return None
        return json.loads(mine.partition('```json\n')[2].partition('\n```')[0])

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
                'slides': [slides_stand_in.sketch(self.said(slide['id']), spec['prefix'])
                           for slide in spec['slides']]}
        for slide in made['slides']:   # copied from the brief, its keys in another order
            intent = self.intent(self.read[spec['prefix']]['brief'], slide['id'])
            slide.update({'intent': json.loads(json.dumps(intent, sort_keys=True))}
                         if intent else {})
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
        self.assertEqual([call for call in self.asked('compose compile')
                          + self.asked('compose preview') if {'--design-project', '--section',
                                                              '--json'} & set(call)], [],
                         'a deck without a design is built as 0.13.1 builds it')
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


class DesignedDeckTests(WholeCase):
    """The same deck through a slides tool with a design session: the outline's writer
    proposes how each slide is drawn, the tool keeps the proposal, and the person's one
    decision on the page is the tool's answer."""

    def setUp(self):
        super().setUp()
        self.slides, self.brand = self.stand_ins(design=True)
        self.tool, self.skill = self.slides.run, self.brand.run
        self.engine.deck_needs(fresh=True)

    def test_a_deck_with_its_design_goes_from_the_handoff_to_approved(self):
        root = self.begin()
        view = self.to_outline(root)
        shown = view['outline']
        self.assertEqual([slide['design']['family'] for slide in shown['slides']], [
            'text', 'diagram', 'diagram', 'text', 'diagram', 'diagram', 'text'])
        self.assertEqual(shown['design']['asked'], [slide['id'] for slide in PARTED['slides']])
        checked = [call for call in self.asked('design propose') if '--expected' not in call]
        self.assertGreaterEqual(len(checked), 3, 'probed, checked by the worker, proposed')
        self.assertEqual(self.asked('design respond'), [])
        status = json.loads(self.tool(['node', 'script', 'design', 'status', '--project',
                                       str(root / pipeline.DESIGNS)])[1])
        self.assertEqual((status['mode'], status['buildAllowed'], status['revision']),
                         ('batch', False, shown['design']['revision']))
        view = self.engine.outline(root, None, 'approve', seen=shown['sha256'],
                                   design=shown['design']['revision'])
        self.assertEqual((view['state'], workspace.status(root)['gate']), ('waiting', 'deck'),
                         view.get('problem'))
        responded = self.asked('design respond')
        self.assertEqual(len(responded), 1)
        self.assertEqual(len(self.asked('design check')), 1)
        session = json.loads((root / pipeline.DESIGNS / '.harness-slides' / 'design' /
                              'session.json').read_text())
        self.assertEqual({approval['response'] for approval in session['approvals'].values()},
                         {'Approve the whole plan'})
        self.assertEqual(len(session['approvals']), len(PARTED['slides']))
        for job in self.base.glob('data/**/drafts/design-*'):
            self.fail(f'a worker check left its project behind: {job}')
        # Each composer copied its intents from its brief, in an order of its own, and every
        # check and preview of a section was made against the design as that section; the
        # whole deck was compiled and previewed against it as the deck.
        project = str(root / pipeline.DESIGNS)
        built = self.asked('compose compile') + self.asked('compose preview')
        sections = [call for call in built if '--design-project' in call and '--section' in call]
        self.assertTrue(sections)
        for call in sections:
            self.assertEqual(call[call.index('--design-project') + 1:][:3],
                             [project, '--section', '--json'])
        whole = [call for call in built if '--design-project' in call and '--section' not in call]
        self.assertEqual([call[1] for call in whole], ['compile', 'preview'])
        unbound = [call for call in built if '--design-project' not in call]
        self.assertEqual([call[-2:] for call in unbound], [['--section', '--json']],
                         'only the question whether it can, asked once')
        for prefix, read in self.composers.read.items():
            self.assertIn('## The approved design', read['brief'])
            self.assertIn('## Icons across the deck', read['brief'])
        self.assertEqual(self.to_end(root), ['deck', 'scenario:main'])


class AssetDeckTests(WholeCase):
    """The same deck through a slides tool that keeps its assets and says what it has: the
    icons the approved design names are found in the brand's library and recorded before
    any section is drawn, and one the brand does not have keeps the deck waiting."""

    def setUp(self):
        super().setUp()
        self.slides, self.brand = self.stand_ins(assets=True)
        self.tool, self.skill = self.slides.run, self.brand.run
        self.engine.deck_needs(fresh=True)

    def approve(self, root: Path) -> dict:
        shown = self.to_outline(root)['outline']
        return self.engine.outline(root, None, 'approve', seen=shown['sha256'],
                                   design=shown['design']['revision'])

    def test_an_icon_the_brand_does_not_have_keeps_the_deck_waiting(self):
        root = self.begin()
        view = self.approve(root)
        self.assertEqual(view['state'], 'waiting')
        self.assertIn('Slide `what-it-does` needs the icon "server" (An instance), and the '
                      "brand's icon library has none by that name.", view['problem']['what'])
        self.assertEqual([entry['state'] for entry in view['deck']['assets']], ['wanted'])
        self.assertEqual(self.asked('outline start'), [])
        self.assertEqual(len(self.asked('design respond')), 1)

    def test_a_deck_draws_the_icons_recorded_for_it_and_is_built_with_its_manifest(self):
        design = runner_support.designed(PARTED)
        design['slides'][1]['asset']['candidates'][0]['ref'] = 'database'
        self.workers.design_said = design
        root = self.begin()
        view = self.approve(root)
        self.assertEqual((view['state'], workspace.status(root)['gate']), ('waiting', 'deck'),
                         view.get('problem'))
        manifest = json.loads((root / pipeline.ASSETS).read_text())
        [icon] = manifest['assets']
        self.assertEqual((icon['assetId'], icon['ref'], icon['provenance']['label']),
                         ('icon_instance', 'ex-database', 'Icon database'))
        recorded = self.asked('assets icon')
        self.assertEqual(recorded[0][:3], ['assets', 'icon', 'ex-database'])
        self.assertIn('--brand', recorded[0])
        for read in self.composers.read.values():
            self.assertIn('- An instance: `ex-database`, recorded as `icon_instance`, on '
                          '`what-it-does`', read['brief'])
        # What the tool has is read from its version: nothing is asked by a refusal.
        self.assertEqual(self.tool.calls.count(['version']), 1)
        built = self.asked('compose compile') + self.asked('compose preview')
        self.assertEqual([call for call in built if '--design-project' not in call], [])
        self.assertEqual(self.asked('design propose')[0][-1], '--json')


class JudgedDeckTests(WholeCase):
    """The same deck through a slides tool that reviews a whole build against the approved
    design: it renders the deck it reviews, the reviewer answers its own criteria, and that
    rendered deck is the one kept."""

    def setUp(self):
        super().setUp()
        self.slides, self.brand = self.stand_ins(assets=True)
        self.tool, self.skill = self.slides.run, self.brand.run
        self.engine.deck_needs(fresh=True)
        design = runner_support.designed(PARTED)
        design['slides'][1]['asset']['candidates'][0]['ref'] = 'database'
        self.workers.design_said = design

    def test_a_deck_is_reviewed_against_its_design_and_the_deck_it_rendered_is_kept(self):
        root = self.begin()
        shown = self.to_outline(root)['outline']
        view = self.engine.outline(root, None, 'approve', seen=shown['sha256'],
                                   design=shown['design']['revision'])
        self.assertEqual((view['state'], workspace.status(root)['gate']), ('waiting', 'deck'),
                         view.get('problem'))
        project, last = str(root / pipeline.DESIGNS), self.built(root)['rounds'][-1]
        review = root / 'work' / 'deck' / last['preview']
        reviewed = [call for call in self.tool.calls if call[:1] == ['review']]
        self.assertEqual(reviewed[0], ['review', '--compiled', str(review.parent / 'compiled'),
                                       '--output', str(review), '--design-project', project,
                                       '--json'])
        self.assertEqual([call[4] for call in reviewed if '--slide' in call][:7],
                         [slide['id'] for slide in PARTED['slides']])
        self.assertEqual(sum('--mark' in call for call in reviewed), 1)
        self.assertEqual(sum('--assessment' in call for call in reviewed), 1)
        # The whole deck is rendered by the review alone: no preview of it, and no critique.
        self.assertEqual([call for call in self.asked('compose preview')
                          if '--section' not in call], [])
        self.assertEqual(self.asked('compose critique'), [])
        record = json.loads((review / 'review.json').read_text())
        self.assertEqual((record['visualReviewComplete'], record['creativeReviewComplete']),
                         (True, True))
        saved = (root / 'deck.pptx').read_bytes()
        self.assertEqual(saved, (review / 'deck.pptx').read_bytes(),
                         'the deck saved is the one the review rendered')
        self.assertEqual(workspace.sha256_file(root / 'deck.pptx'), record['source']['sha256'])
        for number in range(1, 8):
            self.assertEqual(self.engine.picture(root, number, artifact='deck'),
                             next(review.glob(f'slide-{number:03d}-*.png')).read_bytes())
        gate = self.gate(root)
        self.assertEqual(gate['review']['findings'], [])
        self.assertEqual([entry['slide'] for entry in gate['review']['direct']],
                         ['cover-restarts', 'part-two', 'closing-practice'])
        reviewer = [spec for kind, _, spec in self.workers.jobs if kind == 'review'][-1]
        self.assertTrue(reviewer['review']['judged']['packets'])
        self.assertEqual(self.to_end(root), ['deck', 'scenario:main'])


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
                'slides': [slides_stand_in.sketch(self.composers.said(slide['id']),
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
            self.brand.export(folder, brand_stand_in.BRAND, 'light')
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
