"""The slide deck: the runner's own rules for one, the tools its workers have, the flow from
the handoff to an approved deck, and what the page is told and may ask.

The slides tool and a brand skill are the small fakes in runner_support, which follow the
docstrings of the two wrappers and make each kind of trouble easy to cause. Scripted workers
draw and review. test_runner_deck_whole.py takes the same flow through the two modules' own
stand-ins. Nothing starts an agent, the slides tool, a brand skill or Google, and nothing
touches the network.
"""
import json
import threading
from dataclasses import replace
from email.message import Message
from pathlib import Path
from unittest import mock
from urllib.parse import urlencode

import helpers  # noqa: F401
from runner_support import (BLUEPRINT, CHOSEN, NO_BRAND_SKILL, NO_SLIDES, OUTLINE, Brand,
                            JobCase, Slides, StudioCase, drawn, fails, left, png)

import computer
import desk
import workspace
from runner import brand as brand_skill
from runner import briefs, deck, page, pipeline, settings, worker_tools
from runner import slides as slides_tool
from workspace import WorkspaceError

MAJOR = {'slide': 'what-it-does', 'question': 3, 'severity': 'major',
         'note': 'One of two equal labels is set larger than the other.',
         'fix': 'Set both labels alike.'}
SAID = {'slide': 'the-objection', 'question': 4, 'severity': 'major', 'about': 'content',
        'note': 'The caveat pulls away from what the title claims.'}
SMALL = {'slide': 'check-yourself', 'question': 6, 'severity': 'minor',
         'note': 'The last row sits close to the footer.'}


def outline(**changes) -> dict:
    return {**OUTLINE, **changes}


def with_slide(number: int, **changes) -> dict:
    slides = [dict(slide) for slide in OUTLINE['slides']]
    slides[number] = {key: value for key, value in {**slides[number], **changes}.items()
                      if value is not None}
    return outline(slides=slides)


class RuleTests(JobCase):
    def test_a_good_outline_breaks_no_rule(self):
        self.assertEqual(deck.rules(OUTLINE, BLUEPRINT, 90), [])
        self.assertEqual(deck.rules([], BLUEPRINT), [
            'The outline is one JSON object with its slides under "slides".'])

    def test_every_content_slide_names_objectives_and_every_objective_is_served(self):
        self.assertEqual(deck.rules(with_slide(3, sources=['O9']), BLUEPRINT), [
            'the-objection: `sources` names O9, which the blueprint does not have. It may '
            'hold only the objectives this slide serves: O1, O2, O3.'])
        self.assertEqual(deck.rules(with_slide(4, sources=[]), BLUEPRINT), [
            'check-yourself: `sources` is empty. Name the objectives this slide serves, or '
            'leave the slide out.'])
        lost = with_slide(4, sources=['O1'])
        lost['slides'][3]['sources'] = ['O1']
        self.assertEqual(deck.rules(lost, BLUEPRINT), [
            'No slide serves O3. Every objective is named in the `sources` of at least one '
            'content slide.'])

    def test_the_word_budget_counts_everything_a_slide_shows(self):
        slide = OUTLINE['slides'][2]
        self.assertEqual(deck.visible(slide), 8 + (1 + 5) + (1 + 6) + 9)
        self.assertEqual(deck.rules(OUTLINE, BLUEPRINT, 30), [])
        self.assertEqual(deck.rules(OUTLINE, BLUEPRINT, 29)[-1:], [
            'when-capacity-holds: 30 words will be seen, counting the title, the points, the '
            'caveat and the source. The most is 29. Say less, or make it two slides.'])

    def test_a_cover_carries_a_title_and_one_subtitle_line(self):
        self.assertEqual(deck.rules(with_slide(0, detail='A 25-minute lesson'), BLUEPRINT), [
            'cover-restarts: a cover carries a title and one subtitle line, and no more. '
            'Leave out detail.'])
        self.assertEqual(deck.rules(with_slide(0, subtitle='One\nTwo'), BLUEPRINT),
                         ['cover-restarts: the subtitle of a cover is one line.'])

    def test_what_the_blueprint_lists_under_its_open_gaps_stays_out(self):
        self.assertEqual(deck.gaps(BLUEPRINT),
                         {'K1.4': 'Rolling restarts give zero downtime for every app type.'})
        taught = with_slide(3, notes='Rolling restarts give zero  downtime for every app type')
        self.assertEqual(deck.rules(taught, BLUEPRINT), [
            'the-objection: this states K1.4, which the blueprint lists under its open gaps. '
            'Leave it out.'])

    def test_what_is_added_later_is_not_the_workers_to_write(self):
        found = deck.rules(outline(direction={}, house=[], delivery='live'), BLUEPRINT)
        self.assertEqual(found, [
            'Leave out `direction`: it is added after you hand the outline in.',
            'Leave out `house`: it is added after you hand the outline in.',
            'This deck is read alone as well as presented: set `delivery` to "reading".'])

    def test_lead_slides_get_a_layout_that_shows_their_title(self):
        chosen = deck.layouts(Slides.LAYOUTS, OUTLINE['slides'])
        self.assertEqual(chosen, {'cover': 'Title slide', 'closing': 'Closing with title'},
                         'never the closing layout that would drop the title')
        with self.assertRaisesRegex(WorkspaceError, 'no layout that shows the title of a '
                                    'cover slide with its subtitle'):
            deck.layouts(Slides.LAYOUTS[:1], OUTLINE['slides'])
        whole = deck.complete(OUTLINE, Slides.LAYOUTS, ['Approved on the page.'])
        self.assertEqual((whole['direction'], whole['house'], whole['approval']),
                         (deck.DIRECTION, list(deck.HOUSE), ['Approved on the page.']))
        self.assertEqual(deck.lead({'slides': [{'id': 'a', 'detail': 'x'}]}),
                         {'slides': [{'id': 'a'}]})

    def test_the_house_rules_say_what_no_program_can_check(self):
        for told in ('Equals share one size and weight', 'never one of several peers',
                     'Draw nothing the title does not announce'):
            self.assertIn(told, ' '.join(deck.HOUSE))
            self.assertIn(told.split(' ', 1)[1][:20], briefs.guidance('deck-section'))

    def test_a_sections_brief_is_rewritten_for_a_worker_with_tools_and_no_files(self):
        whole = deck.complete(OUTLINE, Slides.LAYOUTS, [])
        written = Slides._brief(whole, 1, whole['slides'][1:3], '/opt/brand/contract.json',
                                Path('/opt/work'))
        given = deck.brief(written, whole)
        for gone in ('/opt/', 'references/', 'Drive', '## Paths', 'None given beyond'):
            self.assertNotIn(gone, given)
        for told in ('`list_inputs` shows what you can read', '## What you write',
                     'handed in with `submit_section`', 'You have 4 previews',
                     '`check_section` is free', 'It must be the version you last previewed',
                     f'- {deck.HOUSE[0]}', '1. **`what-it-does`', '- Batch: Instances are',
                     '## Direction, to copy unchanged', 'Prefix every node and edge ID'):
            self.assertIn(told, given)
        self.assertEqual(deck.named_in(written, whole), ['what-it-does', 'when-capacity-holds'])
        self.assertIn('## Return', deck.brief('# A brief with none of the headings\n', whole))

    def test_a_section_keeps_what_was_fixed_and_every_approved_word(self):
        whole = deck.complete(OUTLINE, Slides.LAYOUTS, [])
        spec = deck.fixed(whole, ['what-it-does', 'when-capacity-holds'], 1)
        good = drawn(spec)
        self.assertEqual(deck.kept(good, spec), [])
        for change, expect in (
                (lambda made: made['slides'][0].update(title='Batches'), 'the title is fixed'),
                (lambda made: made['slides'][0].update(sources=[]), '`sources` is fixed'),
                (lambda made: made['slides'][0].update(notes='Shorter.'),
                 '`notes` stays exactly as it was approved.'),
                (lambda made: made['slides'][1].pop('caveat'),
                 '`caveat` stays exactly as it was approved: "A single-instance'),
                (lambda made: made['slides'][0].update(caveat='New.'),
                 '`caveat` stays exactly as it was approved: the slide has none.'),
                (lambda made: made['slides'][0].update(layout='Title slide'),
                 'names no template layout'),
                (lambda made: made.update(direction={'focal': 'accent'}),
                 '`direction` is copied unchanged'),
                (lambda made: made['slides'][0]['canvas']['children'][0].update(id='mine'),
                 'every node and edge ID starts with s1_. These do not: mine.'),
                (lambda made: made['slides'].reverse(),
                 'The slides are exactly these, in this order')):
            made = json.loads(json.dumps(good))
            change(made)
            self.assertIn(expect, ' '.join(deck.kept(made, spec)))
        reworded = drawn(spec, lambda text: text.replace('one batch', 'a batch'))
        self.assertEqual(deck.kept(reworded, spec), [
            'what-it-does: these approved words are missing or changed: "Instances are '
            'replaced one batch at a time."'])

    def test_only_a_major_finding_about_drawing_sends_a_section_back(self):
        slides = [{'id': slide['id'], 'number': number}
                  for number, slide in enumerate(OUTLINE['slides'], start=1)]
        kept = [deck.checked(finding, slides)[0] for finding in (SMALL, SAID, MAJOR)]
        sections = [{'id': 'section-1', 'slides': ['what-it-does', 'when-capacity-holds']},
                    {'id': 'section-2', 'slides': ['the-objection', 'check-yourself']}]
        self.assertEqual(deck.to_repair(kept, sections), ['section-1'])
        self.assertEqual(deck.to_repair(kept[:2], sections), [])
        self.assertEqual([finding['slide'] for finding in deck.ordered(kept)],
                         ['what-it-does', 'the-objection', 'check-yourself'])
        self.assertEqual(deck.remains(kept), 'This deck is not clear: the review still finds '
                         '2 major things wrong.')
        self.assertEqual(deck.remains(kept[:1]), 'The review found nothing major, and 1 '
                         'small thing worth a look.')
        for wrong, why in (({**MAJOR, 'slide': 'x'}, 'is not a slide of this deck'),
                           ({**MAJOR, 'question': 9}, '`question` is a number from 1 to 8'),
                           ({**MAJOR, 'severity': 'bad'}, '`severity` is one of'),
                           ({**MAJOR, 'note': 'Bad.'}, '`note` is one sentence'),
                           ({**MAJOR, 'about': 'taste'}, '`about` is one of: drawing')):
            self.assertIn(why, deck.checked(wrong, slides)[1])

    def test_a_closing_slide_holds_a_few_words_and_nothing_to_read(self):
        blueprint = BLUEPRINT
        import checks
        objectives = list(checks.parse_blueprint(blueprint)['objectives'])
        content = {'id': 'what-it-is', 'kind': 'content', 'title': 'What it is',
                   'sources': objectives}
        long = {'id': 'closing-practice', 'kind': 'closing',
                'title': 'Practice next: probe-quiz, probe-design and manifest-review, in '
                         'that order, with a partner'}
        short = {'id': 'closing-practice', 'kind': 'closing', 'title': 'Thank you',
                 'subtitle': 'Now practise'}
        told = deck.rules({'slides': [content, long]}, blueprint)
        self.assertTrue(any('closing slide is the brand' in problem and
                            'content slide before it' in problem for problem in told), told)
        self.assertEqual(deck.rules({'slides': [content, short]}, blueprint), [])

    def test_the_handoff_has_the_headings_the_skill_gives_it(self):
        text = deck.handoff('Rolling restarts', '301', BLUEPRINT, {}, 'google',
                            ('example-co', 'light'), True, ['main'])
        self.assertEqual([line for line in text.splitlines() if line.startswith('#')], [
            '# Deck handoff: Rolling restarts, level 301', '## Goal',
            '## Audience and duration', '## Use', '## Required elements', '## Sources',
            '## Research', '## Output'])
        for told in ('- Describe what a rolling restart does (O1)', 'Duration: 25 min',
                     'no slide may depend on its speaker notes', 'M1, Rolling restarts',
                     'says what to practise next: main, then a closing slide.',
                     'The blueprint, the learner guide and the research findings.',
                     "Anything under the blueprint's open gaps stays out.",
                     'Google Slides, in the brand example-co (light).'):
            self.assertIn(told, text)
        self.assertEqual(deck.before(8), {'dollars': 3.2, 'minutes': 10.0})


class ToolCase(JobCase):
    """One job of a deck, with the two stand-ins behind its tools."""

    def setUp(self):
        super().setUp()
        self.slides, self.brand = Slides(), Brand()
        self.contract = self.brand.export(self.base / 'brand', 'example-co', 'light')['contract']
        whole = deck.complete(OUTLINE, Slides.LAYOUTS, [])
        self.spec = {'kind': 'section', 'brand': self.contract,
                     **deck.fixed(whole, ['what-it-does', 'when-capacity-holds'], 1),
                     'previews': 4, 'renderer': 'drive', 'lock': str(self.base / 'render.lock'),
                     'kept': str(self.base / 'preview-file.json'),
                     'named': {'name': 'Preview: Rolling restarts'}}

    def tools(self, **prepared) -> worker_tools.WorkerTools:
        if prepared or not (self.job / 'job.json').exists():
            worker_tools.prepare(self.job, **prepared)
        return worker_tools.WorkerTools(self.job, slides=self.slides, brand=self.brand)

    def composer(self) -> worker_tools.WorkerTools:
        return self.tools(inputs={'brief': 'Your slides.'}, artifacts={'section': self.spec},
                          ask=False)

    def offered(self, tools) -> list[str]:
        return [entry['name'] for entry in tools.offered()]


class OutlineToolTests(ToolCase):
    def writer(self) -> worker_tools.WorkerTools:
        return self.tools(artifacts={'outline': {'kind': 'outline', 'brand': self.contract,
                                                 'blueprint': BLUEPRINT}})

    def test_an_outline_job_has_its_own_tools_and_no_others(self):
        self.assertEqual(self.offered(self.writer()), [
            'list_inputs', 'read_input', 'submit_review', 'check_outline', 'submit_outline',
            'ask_person'])
        with self.assertRaisesRegex(WorkspaceError, 'needs the brand it is checked against'):
            worker_tools.prepare(self.base / 'other', artifacts={'outline': {'kind': 'outline'}})

    def test_an_outline_is_checked_by_the_tool_and_by_the_runners_rules(self):
        tools = self.writer()
        self.assertEqual(self.ok(tools.check_outline(json.dumps(OUTLINE))),
                         'Nothing to put right. Hand it in with submit_outline.')
        bad = with_slide(2, notes=None, sources=['O7'])
        said = self.ok(tools.check_outline(bad))
        self.assertIn('- when-capacity-holds: It has no notes.', said)
        self.assertIn('- when-capacity-holds: `sources` names O7', said)
        self.assertEqual(tools._state()['submissions'], {}, 'a check is never counted')
        self.assertIn('Not accepted', self.refused(tools.submit_outline(json.dumps(bad))))
        self.assertEqual(self.ok(tools.submit_outline(json.dumps(OUTLINE))),
                         'Accepted: outline.')
        handed = worker_tools.collect(self.job)['artifacts']['outline']
        self.assertEqual((handed['kind'], json.loads(handed['text']), handed['path'].suffix),
                         ('outline', OUTLINE, '.json'))
        self.assertEqual([(outcome['check'], outcome['status']) for outcome in handed['checks']],
                         [('outline.tool', 'passed'), ('outline.rules', 'passed')])

    def test_the_tools_budget_is_held_against_everything_a_slide_shows(self):
        self.slides.budget = 29
        said = self.ok(self.writer().check_outline(json.dumps(OUTLINE)))
        self.assertIn('when-capacity-holds: 30 words will be seen', said)
        self.assertNotIn('over-budget', said, 'the tool itself counts the points alone')

    def test_what_the_tool_refuses_is_given_to_the_worker_without_a_folders_name(self):
        tools = self.writer()
        self.slides.refuse['outline_check'] = [
            f"{self.job / 'drafts' / 'outline-1.json'}: a title is too long.",
            f'{Path.home()}/tool: 2 problems to fix.']
        said = self.ok(tools.check_outline(json.dumps(OUTLINE)))
        self.assertIn('- outline-1.json: a title is too long.', said)
        self.assertIn('- ~/tool: 2 problems to fix.', said)
        self.assertNotIn(str(self.base), said)
        self.assertIn('is not valid JSON', self.refused(tools.check_outline('{not json')))

    def test_without_the_slides_tool_the_job_says_so_and_keeps_nothing(self):
        tools = self.writer()
        tools._slides = None
        with mock.patch.object(slides_tool, 'Slides', side_effect=WorkspaceError(NO_SLIDES)):
            self.assertEqual(self.refused(tools.submit_outline(json.dumps(OUTLINE))), NO_SLIDES)
        self.assertEqual(worker_tools.collect(self.job)['artifacts'], {})


class SectionToolTests(ToolCase):
    def test_a_composer_has_its_own_tools_and_no_others(self):
        self.assertEqual(self.offered(self.composer()), [
            'list_inputs', 'read_input', 'check_section', 'preview_section', 'search_icons',
            'submit_section'])

    def test_a_check_compiles_and_holds_the_section_to_what_was_fixed(self):
        tools, good = self.composer(), drawn(self.spec)
        self.assertEqual(self.ok(tools.check_section(json.dumps(good))), 'Nothing to put '
                         'right. Preview it with preview_section before you hand it in.')
        long = drawn(self.spec)
        long['slides'][0]['canvas']['children'].append(
            {'type': 'text', 'id': 's1_more', 'text': 'TOO LONG TO FIT'})
        long['slides'][1]['title'] = 'Another title'
        said = self.ok(tools.check_section(long))
        self.assertIn('- when-capacity-holds: the title is fixed', said)
        self.assertIn('- A text does not fit: it needs 7 lines and has 4.', said)
        self.assertEqual(self.slides.most, 0, 'a check renders nothing')

    def test_a_preview_returns_a_picture_of_every_slide_with_what_the_renderer_found(self):
        tools, good = self.composer(), drawn(self.spec)
        self.slides.findings['when-capacity-holds'] = [
            {'severity': 'warn', 'code': 'density', 'detail': '95 words to read.'}]
        shown = tools.preview_section(json.dumps(good))
        self.assertIsInstance(shown, worker_tools.Shown)
        self.assertEqual(shown[1].splitlines()[:3], [
            'Preview 1 of 4.', '- Slide 1, `what-it-does`. The renderer found: nothing',
            '- Slide 2, `when-capacity-holds`. The renderer found: warn density: 95 words '
            'to read.'])
        self.assertEqual([path.read_bytes() for path in shown.pictures], [png(1), png(2)])
        self.assertEqual(sorted(path.name for path in (self.job / 'shown').iterdir()),
                         ['1.png', '2.png'])
        self.assertFalse(any((self.job / 'builds').iterdir())
                         or any((self.job / 'previews').iterdir()),
                         'a build and a render hold megabytes, and are not kept')
        self.assertEqual(json.loads((self.base / 'preview-file.json').read_text()), {
            'id': 'file-1', 'name': 'Preview: Rolling restarts',
            'url': 'https://docs.example.com/presentation/d/file-1/edit'})
        self.ok(tools.preview_section(json.dumps(good)))
        self.assertEqual(self.slides.files, ['file-1'], 'one preview file, written again')
        self.assertEqual(self.slides.calls[-1][-1], 'file-1')

    def test_a_composer_has_four_previews(self):
        tools, good = self.composer(), json.dumps(drawn(self.spec))
        for _ in range(4):
            self.ok(tools.preview_section(good))
        self.assertEqual(self.refused(tools.preview_section(good)), 'You have used all 4 '
                         'previews. Hand in the version you last previewed, with '
                         'submit_section.')
        self.ok(tools.submit_section(good))

    def test_a_draft_that_cannot_be_drawn_or_rendered_uses_up_no_preview(self):
        tools, good = self.composer(), drawn(self.spec)
        bad = drawn(self.spec, lambda text: text.replace('Traffic', 'Load'))
        said = self.refused(tools.preview_section(json.dumps(bad)))
        self.assertIn('Nothing was rendered, and this did not use up a preview.', said)
        self.slides.refuse['preview'] = ['The render has 8 pages for 2 slides.']
        said = self.refused(tools.preview_section(json.dumps(good)))
        self.assertEqual(said, 'The slides compile but could not be rendered, and this did '
                         'not use up a preview:\n- The render has 8 pages for 2 slides.')
        self.assertEqual(tools._state().get('previews', 0), 0)
        self.assertFalse((self.job / 'shown').exists() and any((self.job / 'shown').iterdir()))
        self.assertFalse((self.base / 'render.lock').exists(), 'the turn is given back')

    def test_what_is_handed_in_must_be_what_was_last_previewed(self):
        tools, good = self.composer(), drawn(self.spec)
        self.assertEqual(self.refused(tools.submit_section(json.dumps(good))), 'Preview the '
                         'section first: what you hand in is what you last looked at.')
        self.ok(tools.preview_section(json.dumps(good)))
        other = drawn(self.spec)
        other['slides'][0]['brief']['rhythm'] = 'dense'
        said = self.refused(tools.submit_section(json.dumps(other)))
        self.assertEqual(said, 'This is not the version you last previewed, and it was not '
                         'counted as a hand-in. Hand in exactly that version, or preview '
                         'this one first: you have 3 previews left.')
        self.assertEqual(tools._state()['submissions'], {})
        self.assertIn('Hand a section in with submit_section',
                      self.refused(tools.submit_artifact('section', json.dumps(good))))
        spaced = json.dumps(good, indent=4)
        self.assertEqual(self.ok(tools.submit_section(spaced, 'I evened the rows.',
                                                      'Slide 2 is crowded.')),
                         'Accepted: section.')
        handed = worker_tools.collect(self.job)
        self.assertEqual(json.loads(handed['artifacts']['section']['text']), good)
        self.assertEqual(handed['review'], 'What I changed after looking: I evened the rows.\n'
                         'What still bothers me: Slide 2 is crowded.\n')
        self.assertEqual((handed['shown']['previews'],
                          [slide['path'].read_bytes() for slide in handed['shown']['slides']]),
                         (1, [png(1), png(2)]))

    def test_a_hand_in_that_changed_an_approved_word_is_never_kept(self):
        tools = self.composer()
        changed = drawn(self.spec)
        changed['slides'][1]['caveat'] = 'A single-instance app may drop requests.'
        self.assertIn('`caveat` stays exactly as it was approved',
                      self.refused(tools.preview_section(json.dumps(changed))))
        tools._slides = mock.Mock(wraps=self.slides)
        home_state = {**tools._state(), 'previewed': tools._digest(changed), 'previews': 1}
        (self.job / 'state.json').write_text(json.dumps(home_state))
        said = self.refused(tools.submit_section(json.dumps(changed)))
        self.assertIn('Not accepted', said)
        self.assertIn('`caveat` stays exactly as it was approved', said)
        self.assertEqual(worker_tools.collect(self.job)['artifacts'], {})

    def test_icons_are_searched_in_the_brands_own_library(self):
        tools = self.composer()
        self.assertEqual(self.ok(tools.search_icons('server')), 'Icons for "server". Use an '
                         'ID as the icon of an icon node:\n- icon-server: Server '
                         '(Hardware)\n- icon-server-rack: Server rack (Hardware)',
                         'one that is a picture cannot be placed, and is not offered')
        self.assertIn('No icon matches "photo"', self.ok(tools.search_icons('photo')))
        self.assertIn('No icon matches "database failover"',
                      self.ok(tools.search_icons('database  failover')))
        self.assertIn('one or two plain words', self.refused(tools.search_icons('')))
        self.brand.refuse['icons'] = ['The icon library could not be read.']
        self.assertIn('The icon library could not be read',
                      self.refused(tools.search_icons('clock')))

    def test_a_jobs_tools_use_the_slides_tool_and_the_brand_skill_the_job_names(self):
        named = {'slides': '/opt/slides-tool/versions/0.13.1', 'brand': '/opt/brand-kit'}
        with mock.patch.object(slides_tool, 'Slides', return_value=self.slides) as tool, \
                mock.patch.object(brand_skill, 'Brand', return_value=self.brand) as skill:
            worker_tools.prepare(self.job, artifacts={'section': self.spec}, runtimes=named)
            tools = worker_tools.WorkerTools(self.job)
            self.ok(tools.check_section(json.dumps(drawn(self.spec))))
            self.ok(tools.search_icons('clock'))
            self.assertEqual((tool.call_args_list, skill.call_args_list),
                             ([mock.call(runtime=named['slides'])],
                              [mock.call(runtime=named['brand'])]))
            # A job that names neither finds them as the runner itself would.
            other = self.base / 'other'
            worker_tools.prepare(other, artifacts={'section': self.spec})
            tools = worker_tools.WorkerTools(other)
            self.ok(tools.check_section(json.dumps(drawn(self.spec))))
            self.ok(tools.search_icons('clock'))
            self.assertEqual((tool.call_args, skill.call_args), (mock.call(), mock.call()))

    def test_previews_wait_for_their_turn_at_the_renderer(self):
        self.slides.took, tools, good = 0.05, self.composer(), json.dumps(drawn(self.spec))
        folders = []
        for number in (2, 3):
            folder = self.base / f'job-{number}'
            worker_tools.prepare(folder, artifacts={'section': self.spec})
            folders.append(worker_tools.WorkerTools(folder, slides=self.slides))
        threads = [threading.Thread(target=each.preview_section, args=(good,))
                   for each in (tools, *folders)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual((self.slides.most, len(self.slides.files)), (1, 1))
        compiled = self.base / 'compiled'
        (self.base / 'whole.json').write_text(json.dumps(drawn(self.spec)))
        self.slides.compile(self.base / 'whole.json', self.contract, compiled)
        loose = [threading.Thread(target=self.slides.preview, args=(
            compiled, self.base / f'loose-{number}', 'drive')) for number in (1, 2)]
        for thread in loose:
            thread.start()
        for thread in loose:
            thread.join()
        self.assertEqual(self.slides.most, 2, 'without the turn, two would have overlapped')

    def test_a_preview_file_made_by_a_render_that_failed_is_still_remembered(self):
        # The slides tool's own line, which is where the module reads `left` from.
        refusal = slides_tool.Refused([
            'The render has 8 pages for 2 slides; check the deck for an import problem The '
            'preview deck is in Drive (https://docs.example.com/presentation/d/file-9/edit); '
            'retry with --file-id file-9.'])
        self.assertEqual(sorted(refusal.left), ['fileId', 'url'])
        tools = self.composer()
        with mock.patch.object(self.slides, 'preview', side_effect=refusal) as asked:
            self.refused(tools.preview_section(json.dumps(drawn(self.spec))))
            self.assertEqual(json.loads((self.base / 'preview-file.json').read_text()), {
                'name': 'Preview: Rolling restarts', 'id': 'file-9',
                'url': 'https://docs.example.com/presentation/d/file-9/edit'})
            self.refused(tools.preview_section(json.dumps(drawn(self.spec))))
            self.assertEqual(asked.call_args.kwargs['file_id'], 'file-9',
                             'the next preview writes that file again')

    def test_a_turn_left_by_a_process_that_ended_is_taken(self):
        lock = self.base / 'render.lock'
        lock.write_text('999999999')
        with worker_tools.one_at_a_time(lock):
            self.assertTrue(lock.is_file())
        self.assertFalse(lock.exists())


class ReviewToolTests(ToolCase):
    def reviewer(self, **more) -> worker_tools.WorkerTools:
        build = self.base / 'whole'
        build.mkdir(exist_ok=True)
        (build / 'composition.json').write_text(json.dumps({
            'title': 'Rolling restarts', 'slides': [
                {'id': slide['id'], 'title': slide['title'], 'layout': 'x',
                 'sources': slide.get('sources')} for slide in OUTLINE['slides']]}))
        if not (build / 'compiled').exists():
            self.slides.compile(build / 'composition.json', self.contract, build / 'compiled')
            self.shown = self.slides.preview(build / 'compiled', build / 'preview', 'local')
        slides = [{key: slide[key] for key in ('number', 'id', 'title', 'image')}
                  for slide in self.shown['slides']]
        return self.tools(inputs={'the review': 'Eight questions.'}, ask=False, review={
            'preview': str(build / 'preview'), 'deck': self.shown['deckSha256'],
            'slides': slides, 'objectives': ['O1', 'O2', 'O3'],
            'recorded': str(build / 'assessment.json')}, **more)

    def test_a_reviewer_looks_at_every_slide_at_full_size_before_handing_in(self):
        tools = self.reviewer()
        self.assertEqual(self.offered(tools), ['list_inputs', 'read_input', 'look_at_slide',
                                               'submit_assessment', 'submit_coverage'])
        self.assertEqual(self.refused(tools.submit_assessment([])), 'Look at every slide '
                         'first. Not looked at yet: 1, 2, 3, 4, 5, 6.')
        looked = tools.look_at_slide(2)
        self.assertEqual((looked[1], [path.read_bytes() for path in looked.pictures]), (
            'Slide 2, `what-it-does`: "A rolling restart replaces instances one batch at a '
            'time".', [png(2)]))
        self.assertIn('numbered 1, 2, 3, 4, 5, 6', self.refused(tools.look_at_slide(9)))
        self.assertNotIn('contact', ' '.join(worker_tools.NAMES))

    def looked(self, **more) -> worker_tools.WorkerTools:
        tools = self.reviewer(**more)
        for number in range(1, 7):
            self.ok(tools.look_at_slide(number))
        return tools

    def test_an_assessment_is_recorded_against_the_render_with_what_each_finding_is_about(self):
        tools = self.looked()
        said = self.refused(tools.submit_assessment([{**MAJOR, 'note': 'Bad.'}], ['nowhere']))
        self.assertIn('what-it-does: `note` is one sentence', said)
        self.assertIn('weakest names up to three slides', said)
        self.assertEqual(self.ok(tools.submit_assessment(json.dumps([MAJOR, SAID]),
                                                         ['what-it-does'])),
                         'Recorded: 2 findings. Now say which slides address each objective, '
                         'with submit_coverage.')
        sent = json.loads((self.base / 'whole' / 'preview' / 'critique.json').read_text())
        self.assertEqual((sent['deckSha256'], sent['reviewer'], sent['findings'][1]), (
            self.shown['deckSha256'], 'independent',
            {key: SAID[key] for key in ('slide', 'question', 'severity', 'note')}))
        kept = worker_tools.collect(self.job)['assessment']
        self.assertEqual([(finding['number'], finding['about']) for finding in kept['findings']],
                         [(2, 'drawing'), (4, 'content')])

    def test_what_the_tool_refuses_in_an_assessment_goes_back_to_the_reviewer(self):
        tools = self.looked()
        self.slides.refuse['critique'] = ['Question 3 was answered twice for one slide.']
        self.assertIn('- Question 3 was answered twice for one slide.',
                      self.refused(tools.submit_assessment([MAJOR])))
        self.assertIsNone(worker_tools.collect(self.job)['assessment'])

    def test_a_render_takes_one_assessment_so_an_earlier_one_stands(self):
        self.ok(self.looked().submit_assessment([MAJOR]))
        self.job = self.base / 'second-try'
        again = self.looked()
        self.assertIn('An assessment was already recorded for this render, and a render takes '
                      'only one, so that one stands.', self.ok(again.submit_assessment([])))
        self.assertEqual(worker_tools.collect(self.job)['assessment']['findings'][0]['slide'],
                         'what-it-does')
        self.assertEqual([call[0] for call in self.slides.calls].count('critique'), 1)

    def test_coverage_names_every_objective_with_slides_of_this_deck(self):
        tools = self.looked()
        self.assertIn('Give every objective and nothing else: O1, O2, O3.',
                      self.refused(tools.submit_coverage({'O1': [2]})))
        self.assertIn('O2: a list of slide numbers from 1 to 6',
                      self.refused(tools.submit_coverage({'O1': [2], 'O2': [7], 'O3': []})))
        self.ok(tools.submit_coverage('{"O1": [3, 2, 2], "O2": [3], "O3": []}', 'As titled.'))
        self.assertEqual(worker_tools.collect(self.job)['coverage'], {
            'objectives': {'O1': [2, 3], 'O2': [3], 'O3': []}, 'reasons': 'As titled.'})

    def test_a_picture_reaches_an_agent_as_an_image_after_the_text(self):
        tools = self.reviewer()
        reply = worker_tools.answer(tools, {'jsonrpc': '2.0', 'id': 7, 'method': 'tools/call',
                                            'params': {'name': 'look_at_slide',
                                                       'arguments': {'number': 3}}})['result']
        self.assertEqual((reply['isError'], [part['type'] for part in reply['content']]),
                         (False, ['text', 'image']))
        image = reply['content'][1]
        self.assertEqual((image['mimeType'], worker_tools.base64.b64decode(image['data'])),
                         ('image/png', png(3)))
        log = [json.loads(line) for line in (self.job / 'tools.log').read_text().splitlines()]
        self.assertEqual((log[-1]['tool'], log[-1]['pictures']), ('look_at_slide', 1))
        plain = worker_tools.answer(tools, {'jsonrpc': '2.0', 'id': 8, 'method': 'tools/call',
                                            'params': {'name': 'list_inputs'}})['result']
        self.assertEqual([part['type'] for part in plain['content']], ['text'])

    def test_only_a_real_picture_is_ever_shown(self):
        tools = self.reviewer()
        Path(self.shown['slides'][0]['image']).write_text('not a picture')
        self.assertEqual(self.refused(tools.look_at_slide(1)), 'That picture cannot be shown.')
        with self.assertRaisesRegex(WorkspaceError, 'outside its own folder'):
            worker_tools.pictures({'slides': [{'number': 1, 'id': 'a',
                                               'image': str(self.base / 'elsewhere.png')}]},
                                  self.base / 'whole' / 'preview', self.base / 'kept')


class DeckCase(StudioCase):
    """A computer that can make a deck: the two stand-ins, and previews through Drive."""

    HOW = 'drive'

    def setUp(self):
        super().setUp()
        self.slides, self.brand = Slides(), Brand()
        settings.save(replace(settings.load(), previews=self.HOW))

    def begin(self, **changes) -> Path:
        return self.start(**{'deck_target': 'pptx', 'brand': CHOSEN, **changes})

    def to_outline(self, root: Path, level: str | None = None) -> dict:
        """Approve what is waiting until what a deck says is put to the person."""
        for _ in range(40):
            view = self.view(root)
            if view['outline'] and view['outline']['waiting'] \
                    and view['outline']['level'] == level:
                return view
            self.assertIsNotNone(workspace.status(root)['gate'], view)
            self.decide(root, workspace.status(root)['gate'])
        self.fail('What the deck says never came up for review')

    def drawn(self, root: Path, level: str | None = None) -> dict:
        """Take a deck to its gate, approving what it says on the way."""
        self.to_outline(root, level)
        return self.engine.outline(root, level, 'approve')

    def kinds(self, since: int = 0) -> list[str]:
        return [kind for kind, _, _ in self.workers.jobs[since:]]

    def gate(self, root: Path, name: str = 'deck') -> dict:
        return page.RunnerPage(8765, self.engine).gate(str(root), name)

    def built(self, root: Path, level: str | None = None) -> dict:
        return pipeline.read_built(root, level)

    def deck_steps(self, root: Path) -> dict:
        return {step['id']: step['status'] for step in self.view(root)['steps']
                if 'deck' in step['id']}


class FlowTests(DeckCase):
    def test_a_deck_goes_from_the_handoff_to_approved_as_powerpoint(self):
        root = self.begin()
        view = self.to_outline(root)
        self.assertEqual((view['state'], view['sentence']), (
            'waiting', 'What the slide deck says is waiting for your review. A deck of 6 '
            'slides has cost about $2.40 and 7.5 minutes of agent time to draw before, and as '
            'much again each time its slides were drawn again after a review.'))
        self.assertEqual(self.kinds()[-3:], ['document', 'brief', 'outline'],
                         'the deck has its place after the brief and before the scenarios')
        self.assertIn('## Required elements', (root / 'deck-handoff.md').read_text())
        self.assertEqual(json.loads((root / 'deck' / 'outline.json').read_text()), OUTLINE)
        self.assertEqual(self.brand.exports[-1][1:], ('example-co', 'light', 'reading'))
        self.assertIsNone(workspace.status(root)['gate'], 'the core has no gate for it')
        view = self.engine.outline(root, None, 'approve')
        self.assertEqual((view['state'], view['sentence'], workspace.status(root)['gate']),
                         ('waiting', 'The slide deck is waiting for your review.', 'deck'))
        self.assertEqual(sorted(self.kinds()[-3:]), ['review', 'section', 'section'])
        self.assertEqual(set(self.deck_steps(root).values()) - {'done'}, {'waiting'})
        self.assertEqual(self.deck_steps(root)['gate:deck'], 'waiting')
        saved = (root / 'deck.pptx').read_bytes()
        last = self.built(root)['rounds'][-1]
        self.assertEqual(saved, (root / 'work' / 'deck' / last['file']).read_bytes(),
                         'the deck that is saved is the deck that was previewed')
        self.assertEqual(workspace.sha256_file(root / 'deck.pptx'), last['deck'])
        self.assertEqual(self.brand.audited, [(saved, 'example-co', 'light')])
        self.assertNotIn('render', [call[0] for call in self.slides.calls],
                         'a fresh render would be another file than the one reviewed')
        entry = workspace.load(root)['artifacts']['deck']
        self.assertEqual(entry['reviewed_coverage']['objectives'],
                         {'O1': [2], 'O2': [3], 'O3': [4]})
        self.assertEqual(self.to_end(root), ['deck', 'scenario:main'])
        view = self.view(root)
        self.assertEqual((view['state'], view['finished']['ready'],
                          view['finished']['limitations'], view['outline'], view['deck']),
                         ('done', True, [], None, None))
        self.assertEqual(workspace.status(root)['artifacts']['deck'], 'approved')

    def test_every_step_of_a_deck_is_a_commit_and_nothing_built_is_shared(self):
        self.engine = self.make(at_once=1)
        root = self.begin()
        self.drawn(root)
        self.assertEqual([line.partition(': ')[2] for line in self.log()][-12:], [
            'write the handoff for the slide deck', 'export the brand for the slide deck',
            'keep what the slide deck says', 'ask for a review of what the slide deck says',
            'What the slide deck says was approved on the page.',
            'split the slide deck into 2 sections', 'keep section 1 of the slide deck',
            'keep section 2 of the slide deck', 'put the slide deck together: 6 slides',
            'keep the review of the slide deck', 'keep the slide deck',
            'ask for a review of the slide deck'])
        tracked = self.git('ls-files', 'trainings/rolling-restarts').splitlines()
        self.assertEqual([name for name in tracked if 'work/' in name], [])
        for kept in ('deck.pptx', 'deck-handoff.md', 'deck/outline.json', 'deck/review.json',
                     'reviews/deck.md'):
            self.assertIn(f'trainings/rolling-restarts/{kept}', tracked)
        self.assertEqual(self.git('status', '--porcelain'), '')
        work = root / 'work' / 'deck'
        self.assertEqual(sorted(path.name for path in (work / 'preview').iterdir()),
                         ['1.png', '2.png', '3.png', '4.png', '5.png', '6.png', 'about.json'])
        self.assertEqual(len(list(work.glob('start-*/whole-*'))), 1)

    def test_a_deck_for_google_slides_is_the_previewed_deck_imported(self):
        root = self.begin(deck_target='google')
        self.drawn(root)
        last = self.built(root)['rounds'][-1]
        self.assertEqual(self.slides.imported,
                         [(root / 'work' / 'deck' / last['file']).read_bytes()])
        link = (root / 'deck-link.md').read_text()
        self.assertEqual(link, '# Slide deck: Rolling restarts\n\n- URL: '
                         'https://docs.example.com/presentation/d/slides-1/edit\n- Title: '
                         'Rolling restarts\n- ID: slides-1\n- Made from the rendered deck '
                         f"with the SHA-256 {last['deck']}\n")
        self.assertFalse((root / 'deck.pptx').exists())
        self.assertEqual(len(self.gate(root)['slides']), 6)
        self.assertEqual(self.to_end(root), ['deck', 'scenario:main'])

    def test_with_levels_each_deck_is_made_in_its_own_place(self):
        root = self.begin(levels=['101', '201'])
        self.to_outline(root, '101')
        self.assertEqual([step for step in self.steps(root) if 'deck' in step][:3],
                         ['deck-handoff@101', 'deck-brand@101', 'deck-outline@101'])
        view = self.engine.outline(root, '101', 'approve')
        self.assertEqual((workspace.status(root)['gate'], view['deck']['level']),
                         ('deck@101', '101'))
        self.assertTrue((root / '101' / 'deck.pptx').is_file())
        self.assertTrue((root / '101' / 'work' / 'deck' / 'preview' / '1.png').is_file())
        with self.assertRaisesRegex(WorkspaceError, 'is not waiting for a decision'):
            self.engine.outline(root, '201', 'approve')
        self.decide(root, 'deck@101')
        self.drawn(root, '201')
        self.assertEqual(workspace.status(root)['gate'], 'deck@201')
        self.assertIn('deck@201', self.to_end(root))
        self.assertEqual(self.view(root)['finished']['ready'], True)
        self.assertEqual(len(self.slides.files), 2, 'each deck keeps one preview file')

    def test_it_says_at_least_how_often_it_will_ask(self):
        form = pipeline.check_form({**self.form(), 'levels': ['101', '201']},
                                   self.engine.brands())
        self.assertEqual(self.engine.start(form)['gates'], 12)
        self.slides = None
        self.engine.deck_needs(fresh=True)
        form = pipeline.check_form({**self.form(), 'title': 'Health checks'}, None)
        self.assertEqual(self.engine.start(form)['gates'], 5)

    def form(self) -> dict:
        from runner_support import FORM
        return {**FORM, 'deck_target': 'pptx', 'brand': CHOSEN}

    def test_the_engine_never_approves_what_a_deck_says(self):
        root = self.begin()
        self.to_outline(root)
        for _ in range(3):
            self.engine.wake(root)
            self.engine.resume()
        self.assertNotIn('approved', self.record(root)['deck'][''])
        self.assertEqual(self.kinds().count('section'), 0)
        with self.assertRaisesRegex(WorkspaceError, 'can be decided as: approve, revise'):
            self.engine.outline(root, None, 'accept')
        with self.assertRaisesRegex(WorkspaceError, 'has changed since it was opened'):
            self.engine.outline(root, None, 'approve', seen='0' * 64)
        self.engine.outline(root, None, 'approve', seen=self.view(root)['outline']['sha256'])
        self.assertEqual(self.record(root)['deck']['']['approved']['by'], 'page')

    def test_asking_for_changes_to_what_it_says_has_it_written_again(self):
        root = self.begin()
        self.to_outline(root)
        with self.assertRaisesRegex(WorkspaceError, 'Say what should change'):
            self.engine.outline(root, None, 'revise', '  ')
        shorter = with_slide(4, title='Check what you can explain')
        self.workers.outline_said = shorter
        view = self.engine.outline(root, None, 'revise', 'Shorten the check slide.')
        task = self.workers.of('outline')[-1].task
        self.assertIn('You are revising an earlier draft. What the person asked for:\n\n'
                      'Shorten the check slide.', task)
        self.assertIn('"Check what you can now explain"', task)
        self.assertEqual((view['outline']['waiting'], view['outline']['note'],
                          view['outline']['slides'][4]['title']),
                         (True, 'Shorten the check slide.', 'Check what you can explain'))
        self.assertIn('This version was written because you asked for changes: Shorten the '
                      'check slide.', view['outline']['worth'])
        self.assertEqual(self.kinds().count('section'), 0)
        self.engine.outline(root, None, 'approve')
        self.assertEqual(workspace.status(root)['gate'], 'deck')

    def test_the_writers_are_given_the_brands_naming_rules(self):
        root = self.begin()
        self.to_outline(root)
        for kind in ('document', 'brief', 'outline'):
            job, spec = [(job, spec) for seen, job, spec in self.workers.jobs
                         if seen == kind][-1]
            self.assertIn('naming rules', [entry['name'] for entry in spec['inputs']], kind)
            self.assertIn('"naming rules"', job.task)
        self.assertIn('## Names', self.workers.of('document')[-1].guidance)
        self.assertIn('take no tone', self.workers.of('brief')[-1].guidance)
        blueprint = [spec for seen, _, spec in self.workers.jobs if seen == 'blueprint'][-1]
        self.assertNotIn('naming rules', [entry['name'] for entry in blueprint['inputs']])
        self.engine.outline(root, None, 'approve')
        self.to_gate(root, 'scenario:main')
        self.assertIn('## Names', self.workers.of('scenario')[-1].guidance)
        plain = self.start(title='Health checks')
        self.to_gate(plain, 'document')
        self.assertNotIn('## Names', self.workers.of('document')[-1].guidance)

    def test_each_job_of_a_deck_is_told_what_it_needs_and_given_only_its_tools(self):
        self.engine = self.make(at_once=1)
        root = self.begin()
        self.drawn(root)
        jobs = {kind: (job, spec) for kind, job, spec in self.workers.jobs}
        job, spec = jobs['outline']
        self.assertEqual([entry['name'] for entry in spec['inputs']], [
            'handoff', 'outline contract', 'drafting guidance', 'blueprint',
            'learner guide', 'research findings', 'naming rules'])
        self.assertEqual(job.guidance, briefs.guidance('deck-outline'))
        job, spec = jobs['section']
        self.assertEqual(([entry['name'] for entry in spec['inputs']], spec['ask']),
                         (['brief', 'composition contract', 'design guidance',
                           'composition guidance', 'gallery', 'example contrast',
                           'example order'], False))
        self.assertEqual(spec['runtimes'], {'slides': str(self.slides.runtime),
                                            'brand': str(self.brand.runtime)})
        made = spec['artifacts']['section']
        self.assertEqual((made['previews'], made['renderer'], made['prefix'],
                          Path(made['lock']).name), (4, 'drive', 's2_', 'render.lock'))
        brief = next((root / 'work' / 'deck').glob('start-*/given/section-2.md')).read_text()
        self.assertIn('handed in with `submit_section`', brief)
        self.assertNotIn(str(self.base), brief)
        job, spec = jobs['review']
        self.assertEqual((job.guidance, spec['artifacts'], len(spec['review']['slides'])),
                         (briefs.guidance('deck-review'), {}, 6))
        self.assertIn('1. After three seconds', deck.asked({'O1': 'x'}, [], None))
        for kind in ('outline', 'section', 'review'):
            self.assertEqual(jobs[kind][0].profile, 'write', 'no worker of a deck has the web')

    def test_a_composer_is_given_an_example_only_of_the_relations_its_own_slides_have(self):
        self.workers.outline_said = with_slide(4, relation='parallel')
        self.slides.READING = {**Slides.READING, 'example parallel': '{}\n',
                               'example quantity': '{}\n'}
        self.engine = self.make(at_once=1)
        root = self.begin()
        self.drawn(root)
        first, second = [[entry['name'] for entry in spec['inputs']]
                         for kind, _, spec in self.workers.jobs if kind == 'section']
        self.assertEqual(first[2:], ['design guidance', 'composition guidance', 'gallery',
                                     'example contrast', 'example order'])
        self.assertEqual(second[2:], ['design guidance', 'composition guidance', 'gallery',
                                      'example contrast', 'example parallel'])
        for kind in ('section', 'review'):
            names = [entry['name'] for seen, _, spec in self.workers.jobs if seen == kind
                     for entry in spec['inputs']]
            self.assertNotIn('drafting guidance', names, kind)

    def test_guidance_the_installed_tool_does_not_have_is_left_out(self):
        self.slides.READING = {'design guidance': 'Design from the claim.\n'}
        root = self.begin()
        self.drawn(root)
        jobs = {kind: spec for kind, _, spec in self.workers.jobs}
        self.assertEqual([entry['name'] for entry in jobs['section']['inputs']],
                         ['brief', 'composition contract', 'design guidance'])
        self.assertNotIn('drafting guidance',
                         [entry['name'] for entry in jobs['outline']['inputs']])


class RepairTests(DeckCase):
    def test_a_major_finding_about_drawing_has_its_section_drawn_again(self):
        self.workers.found = [[MAJOR, SMALL]]
        root = self.begin()
        self.drawn(root)
        self.assertEqual(self.kinds()[-6:], ['outline', 'section', 'section', 'review',
                                             'section', 'review'])
        job, spec = [(job, spec) for kind, job, spec in self.workers.jobs
                     if kind == 'section'][-1]
        self.assertEqual(spec['artifacts']['section']['prefix'], 's1_',
                         'only the section with the finding')
        self.assertIn('Draw section 1 of the slide deck again.', job.task)
        self.assertEqual(job.guidance, briefs.guidance('deck-section', repair=True))
        self.assertEqual([entry['name'] for entry in spec['inputs']], [
            'brief', 'composition contract', 'design guidance', 'composition guidance',
            'gallery', 'example contrast', 'example order', 'what the review found',
            'your earlier section'])
        self.assertEqual([slide['number'] for slide in spec['look']], [2, 3])
        review = [job for kind, job, _ in self.workers.jobs if kind == 'review'][-1]
        self.assertFalse(Path(job.folder).exists() or Path(review.folder).exists(),
                         'a job whose result is kept leaves no folder')
        shown = self.gate(root)
        self.assertEqual((shown['review'], workspace.status(root)['gate']),
                         ({'round': 2, 'findings': []}, 'deck'))
        self.assertIn('The slides were drawn again 1 time after a review, which is as often '
                      'as the review asked.',
                      (root / 'reviews' / 'deck.md').read_text().replace('> ', ''))
        self.assertEqual(self.log()[-5].partition(': ')[2],
                         'keep section 1 of the slide deck, drawn again')

    def test_a_later_review_is_told_what_was_found_before(self):
        self.workers.found = [[MAJOR], []]
        root = self.begin()
        self.drawn(root)
        self.assertEqual(self.kinds().count('review'), 2)
        work = pipeline.review_work(root, self.engine._survey(root, self.record(root)),
                                    pipeline.gate_for('deck'), None)
        self.assertIn('## What an earlier review found', work.prepared['inputs']['the review'])
        self.assertIn('Slide `what-it-does`, major, question 3',
                      work.prepared['inputs']['the review'])

    def test_after_two_rounds_the_deck_goes_to_its_gate_with_what_remains(self):
        self.workers.found = [[MAJOR], [MAJOR], [MAJOR, SMALL]]
        root = self.begin()
        view = self.drawn(root)
        self.assertEqual((self.kinds().count('review'), self.kinds().count('section')), (3, 4))
        self.assertEqual((view['state'], workspace.status(root)['gate']), ('waiting', 'deck'))
        shown = self.gate(root)
        self.assertEqual(shown['review']['round'], 3)
        self.assertEqual(shown['review']['findings'], [
            {'slide': 'what-it-does', 'number': 2, 'severity': 'major', 'about': 'drawing',
             'note': MAJOR['note'], 'fix': MAJOR['fix']},
            {'slide': 'check-yourself', 'number': 5, 'severity': 'minor', 'about': 'drawing',
             'note': SMALL['note'], 'fix': None}])
        note = (root / 'reviews' / 'deck.md').read_text().replace('> ', '')
        self.assertIn('This deck is not clear: the review still finds 1 major thing wrong.',
                      note)
        self.assertIn('- Slide 2, major, about how it is drawn: One of two equal labels',
                      note)
        self.assertIn('drawn again 2 times after a review, which is as often as they may be.',
                      note)
        self.assertNotIn('nothing major', note)

    def test_a_finding_about_what_a_slide_says_is_kept_for_the_person(self):
        self.workers.found = [[SAID]]
        root = self.begin()
        self.drawn(root)
        self.assertEqual((self.kinds().count('section'), self.kinds().count('review')), (2, 1),
                         'no composer is asked to change approved words')
        shown = self.gate(root)
        self.assertEqual([(finding['slide'], finding['about']) for finding
                          in shown['review']['findings']], [('the-objection', 'content')])
        note = (root / 'reviews' / 'deck.md').read_text().replace('> ', '')
        self.assertIn('- Slide 4, major, about what it says: The caveat pulls away', note)
        self.assertIn('A finding about what a slide says is yours to settle. Ask for changes '
                      'here', note)
        self.assertIn('This deck is not clear', note)
        self.assertIn('revise', shown['decisions'])
        self.workers.outline_said = with_slide(3, title='Zero downtime needs several instances')
        self.decide(root, 'deck', 'revise', 'Fix the fourth slide.')
        view = self.view(root)
        self.assertEqual((view['outline']['waiting'], view['outline']['slides'][3]['title']),
                         (True, 'Zero downtime needs several instances'))
        task = self.workers.of('outline')[-1].task
        self.assertIn('Fix the fourth slide.', task)
        self.assertIn('- the-objection: The caveat pulls away from what the title claims.',
                      task)
        self.engine.outline(root, None, 'approve')
        self.assertEqual((workspace.status(root)['gate'], self.kinds().count('section')),
                         ('deck', 4))
        self.assertIn('This version was made because you asked for changes: Fix the fourth '
                      'slide.', (root / 'reviews' / 'deck.md').read_text())
        self.assertEqual(self.to_end(root), ['deck', 'scenario:main'])

    def test_a_section_that_fails_three_times_stops_the_training(self):
        self.workers.then('section', fails(), fails(), fails(), fails(), fails(), fails())
        root = self.begin()
        view = self.drawn(root)
        self.assertEqual(view['state'], 'failed')
        self.assertIn('This step did not work in 3 tries: Draw section', view['problem']['what'])
        self.assertIn('failed', [section['state'] for section in view['deck']['sections']])
        view = self.engine.act(root, 'retry')
        self.assertEqual((view['state'], workspace.status(root)['gate']), ('waiting', 'deck'))

    def test_a_blueprint_changed_and_approved_again_has_the_deck_made_again(self):
        root = self.begin()
        self.drawn(root)
        self.decide(root, 'deck')
        self.to_end(root)
        self.workers.blueprint_text = BLUEPRINT.replace('three-instance', 'four-instance')
        self.workers.outline_said = with_slide(1, notes='6 min. Walk the four-instance example.')
        self.decide(root, 'blueprint', 'revise', 'Use four instances.')
        view = self.to_outline(root)
        self.assertTrue(view['outline']['waiting'], view['sentence'])
        self.assertIn('What the outline was made from has changed since the earlier draft',
                      self.workers.of('outline')[-1].task)


class TroubleTests(DeckCase):
    def test_previews_are_taken_one_at_a_time_whatever_is_drawn_side_by_side(self):
        self.slides.took = 0.04
        self.engine = self.make(at_once=3)
        root = self.begin()
        self.drawn(root)
        self.assertEqual(self.kinds().count('section'), 2)
        self.assertEqual((self.slides.most, self.slides.files), (1, ['file-1']))
        self.assertEqual(self.engine.previews_left(), [{
            'name': 'Preview: Rolling restarts', 'training': 'Rolling restarts',
            'url': 'https://docs.example.com/presentation/d/file-1/edit'}])

    def test_a_render_that_fails_leaves_nothing_behind(self):
        root = self.begin()
        self.to_outline(root)

        def broken(compiled, folder, renderer, file_id=None, slide=None):
            Path(folder).mkdir(parents=True)
            (Path(folder) / 'deck.pptx').write_bytes(b'PK\x03\x04 cut short')
            raise slides_tool.Refused(['unbound prefix: line 1, column 786'])

        self.engine = self.make(at_once=1)
        whole = self.slides.preview
        self.workers.then('section', *[self.keeping(whole)] * 2)
        with mock.patch.object(self.slides, 'preview', broken):
            view = self.engine.outline(root, None, 'approve')
        self.assertEqual(view['state'], 'failed')
        self.assertEqual(view['problem']['what'], 'The slides could not be put together and '
                         'rendered. The slides tool refused: unbound prefix: line 1, column '
                         '786 Nothing of that try was kept.')
        work = root / 'work' / 'deck'
        self.assertEqual(list(work.glob('start-*/whole-*')), [])
        self.assertFalse((work / 'preview').exists())
        self.assertFalse((root / 'deck.pptx').exists())
        self.assertEqual(self.built(root)['rounds'], [])
        self.assertEqual(self.git('status', '--porcelain'), '')
        view = self.engine.act(root, 'retry')
        self.assertEqual((view['state'], workspace.status(root)['gate']), ('waiting', 'deck'))

    def keeping(self, preview):
        """A composer whose own previews still work while the whole deck's does not."""
        def act(tools, job):
            with mock.patch.object(self.slides, 'preview', preview):
                self.workers.section(tools, job)
        return act

    def test_a_brand_that_changed_underneath_stops_the_deck_and_says_so(self):
        root = self.begin()
        self.to_outline(root)
        self.brand.revision = 2
        view = self.engine.outline(root, None, 'approve')
        self.assertEqual((view['state'], view['problem']['action']), ('stopped', 'retry'))
        self.assertEqual(view['problem']['what'], 'The brand changed underneath this deck '
                         "after it was exported. The brand skill refused: The brand's own "
                         'files have changed since this was exported. Try again to export it '
                         'afresh. The slides are then drawn again from what you approved the '
                         'deck should say.')
        self.assertEqual(self.kinds().count('section'), 0)
        view = self.engine.act(root, 'retry')
        self.assertEqual((view['state'], workspace.status(root)['gate']), ('waiting', 'deck'))
        self.assertEqual(len(self.brand.exports), 4, 'two writers, the deck, and the deck '
                         'again')
        self.assertEqual(len(list((root / 'work' / 'deck').glob('brand-*'))), 1)

    def test_a_computer_with_nothing_for_a_deck_says_what_is_missing(self):
        self.slides = self.brand = None
        root = self.begin(brand=None)
        self.assertEqual(self.to_end(root), ['research-plan', 'research', 'blueprint',
                                             'document', 'brief', 'scenario:main'])
        view = self.view(root)
        says = left(pipeline.DECK_LEFT, NO_SLIDES, NO_BRAND_SKILL)
        self.assertEqual((view['state'], view['sentence'], view['outline'], view['deck']),
                         ('done', says, None, None))
        self.assertEqual(view['deck_left'], {'says': says, 'artifact': 'deck'})
        self.assertNotIn('not automated', says)
        self.assertEqual([step for step in self.steps(root) if 'deck' in step], ['deck'])

    def test_each_thing_a_deck_needs_is_said_in_a_sentence_with_what_to_do(self):
        def missing(**have) -> list[str]:
            self.slides.have.update(have)
            return self.engine.deck_needs(fresh=True)['missing']

        self.assertEqual(missing(), [])
        self.assertEqual(missing(drive=False), [
            'Previews are set to go through Google Drive, and Google access from this '
            'computer does not reach Drive. Sign in to Google with Drive access, or choose '
            'LibreOffice in Settings.'])
        settings.save(replace(settings.load(), previews='local'))
        self.assertEqual(missing(drive=True), [
            'Previews are set to be rendered with LibreOffice, which this computer does not '
            'have. Install it, or choose Google Drive in Settings.'])
        settings.save(replace(settings.load(), previews=None))
        self.assertIn('has not been chosen. Choose Google Drive or LibreOffice in Settings.',
                      missing()[0])
        self.assertIn('no way to render previews', missing(drive=False)[0])
        self.assertEqual((missing(local=True), self.engine.deck_needs()['how']), ([], 'local'),
                         'LibreOffice sends nothing anywhere, so it needs no choosing')
        self.assertIn('turn a render into pictures', missing(pictures=False)[0])
        with mock.patch.object(Slides, 'VERSION', '0.12.9'):
            self.assertEqual(missing(pictures=True), [
                'The slides tool on this computer is version 0.12.9, and a deck needs '
                f'{slides_tool.MINIMUM} or newer. Update it.'])
        self.brand = None
        self.assertEqual(missing(), [NO_BRAND_SKILL])

    def test_a_computer_with_no_renderer_takes_the_training_through_everything_else(self):
        self.slides.have['drive'] = False
        root = self.begin()
        self.to_end(root)
        view = self.view(root)
        self.assertEqual(view['deck_left']['says'], left(pipeline.DECK_LEFT, engine_no_drive()))
        self.assertEqual(self.kinds().count('outline'), 0)
        self.slides.have['drive'] = True
        self.engine.look_again()
        view = self.view(root)
        self.assertEqual((view['deck_left'], view['outline']['waiting']), (None, True),
                         'put right, a new look lets the deck be made')

    def test_a_training_with_no_brand_chosen_cannot_have_a_deck_made(self):
        root = self.begin()
        session = workspace.load(root)
        session['settings']['brand'] = 'Our usual look'    # as a conversation once wrote it
        workspace.store(root, session)
        self.to_end(root)
        self.assertEqual(self.view(root)['deck_left']['says'],
                         left(pipeline.DECK_LEFT, pipeline.NO_BRAND))
        workspace.checkpoint(root, brand='another-co/light')
        self.assertIn('The brand this training names, another-co in its variant light, is '
                      'not one the brand skill on this computer has.',
                      self.view(root)['deck_left']['says'])

    def test_a_deck_saved_elsewhere_has_nothing_left_before_its_gate(self):
        root = self.begin()
        self.drawn(root)
        import shutil
        shutil.rmtree(root / 'work')
        self.engine = self.make()
        found = self.engine._survey(root, self.record(root))
        self.assertEqual(found.next.kind, 'wait', 'the deck is not built again')
        shown = self.gate(root)
        self.assertEqual((shown['slides'], shown['review']['round'], shown['audit']['status']),
                         ([], 1, 'warnings'))
        self.assertEqual(self.to_end(root), ['deck', 'scenario:main'])


def engine_no_drive() -> str:
    from runner import engine
    return engine.NO_DRIVE


class PageTests(DeckCase):
    PORT = 8765

    def setUp(self):
        super().setUp()
        for patcher in (mock.patch.object(computer, 'run', self.never),
                        mock.patch.object(computer, 'reach', self.never)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.page = page.RunnerPage(self.PORT, self.engine)

    @staticmethod
    def never(*args, **kwargs):
        raise AssertionError('A test must never look at the real computer.')

    def headers(self, token=True, post=False) -> Message:
        made = Message()
        made['Host'] = f'127.0.0.1:{self.PORT}'
        if token:
            made[desk.TOKEN_HEADER] = self.page.token
        if post:
            made['Origin'], made['Content-Type'] = f'http://127.0.0.1:{self.PORT}', \
                'application/json'
        return made

    def ask(self, method: str, target: str, sent=None, token=True):
        body = None if sent is None else json.dumps(sent).encode()
        try:
            status, kind, data = self.page.answer(target, self.headers(token, method == 'POST'),
                                                  method, body)
        except desk.Refusal as refusal:
            return int(refusal.status), None, {'error': str(refusal)}
        except WorkspaceError as refusal:
            return 409, None, {'error': str(refusal)}
        return int(status), kind, data if kind == page.PNG else json.loads(data)

    def get(self, endpoint: str, expect: int = 200, **params):
        status, _, reply = self.ask('GET', f'/api/{endpoint}?{urlencode(params)}')
        self.assertEqual(status, expect, reply)
        return reply

    def post(self, endpoint: str, sent: dict, expect: int = 200):
        status, _, reply = self.ask('POST', f'/api/{endpoint}', sent)
        self.assertEqual(status, expect, reply)
        return reply

    def test_set_up_says_how_previews_are_rendered_and_which_brand_was_found(self):
        found = self.get('setup')
        self.assertEqual(found['previews'], {'how': 'drive', 'drive': True, 'local': False,
                                             'left': []})
        self.assertEqual(found['brand'], {
            'found': True, 'name': 'Example Co brand kit', 'problem': None,
            'brands': [{'brand': 'example-co', 'name': 'Example Co',
                        'variants': ['light', 'dark']}],
            'skills': [{'name': 'Example Co brand kit', 'path': '/opt/brand-kit',
                        'chosen': True}]})
        self.slides.have['local'] = True
        made = self.post('setup', {'previews': 'local', 'brand_skill': '/opt/brand-kit'})
        self.assertEqual((made['previews']['how'], made['previews']['local'],
                          settings.load().previews, settings.load().brand_skill),
                         ('local', True, 'local', '/opt/brand-kit'))
        self.assertEqual(self.post('setup', {})['previews']['how'], 'local')
        self.assertIn('one of these ways: drive, local',
                      self.post('setup', {'previews': 'cloud'}, 400)['error'])
        self.assertIn('from those found on this computer',
                      self.post('setup', {'brand_skill': '/somewhere/else'}, 409)['error'])

    def test_drive_is_not_asked_while_libreoffice_makes_the_previews(self):
        self.slides.have['local'] = True
        self.post('setup', {'previews': 'local'})
        self.slides.calls.clear()
        needs = self.engine.deck_needs(fresh=True)
        self.assertNotIn('drive_check', [name for name, *_ in self.slides.calls])
        # Drive is said to be not asked, never to be missing, and is still offered at set-up.
        previews, = [item for item in needs['items'] if item['id'] == 'deck-previews']
        self.assertEqual((previews['state'], previews['facts'][1]),
                         ('ok', {'label': 'Google Drive', 'state': 'unknown',
                                 'detail': 'not asked, as LibreOffice makes them'}))
        self.assertEqual(needs['missing'], [])
        self.assertEqual(self.get('setup')['previews'],
                         {'how': 'local', 'drive': None, 'local': True, 'left': []})
        # Choosing Drive asks it again.
        self.post('setup', {'previews': 'drive'})
        self.assertIn('drive_check', [name for name, *_ in self.slides.calls])
        self.assertIs(self.get('setup')['previews']['drive'], True)

    def test_one_look_at_this_computer_is_taken_at_a_time_and_reused(self):
        looked, entered, go = [], threading.Event(), threading.Event()
        real = slides_tool.ready

        def slow(*given, **named):
            looked.append(1)
            entered.set()
            go.wait(30)
            return real(*given, **named)

        self.engine._looked = None
        with mock.patch.object(slides_tool, 'ready', slow):
            asking = [threading.Thread(target=self.engine.deck_needs, daemon=True)
                      for _ in range(3)]
            for thread in asking:
                thread.start()
            self.assertTrue(entered.wait(30))
            go.set()
            for thread in asking:
                thread.join(30)
            self.engine.brand_skills()
        self.assertEqual(len(looked), 1)

    def test_the_brand_is_a_choice_among_those_the_brand_skill_has(self):
        from runner_support import FORM
        wanted = {**FORM, 'deck_target': 'pptx'}
        for brand, why in ((None, 'Choose a brand for the deck, or choose no deck.'),
                           ('Example Co', 'Give the brand as its name and its variant'),
                           ({'brand': 'example-co'}, 'The brand is one of: example-co (light'),
                           ({'brand': 'example-co', 'variant': 'sepia'}, 'The brand is one of'),
                           ({'brand': 'other', 'variant': 'light'}, 'The brand is one of')):
            self.assertIn(why, self.post('trainings', {**wanted, 'brand': brand}, 400)['error'])
        made = self.post('trainings', {**wanted, 'brand': {'brand': 'example-co',
                                                           'variant': 'dark'}})
        self.assertEqual(made['gates'], 7)
        self.assertEqual(workspace.load(Path(made['path']))['settings']['brand'],
                         'example-co/dark')
        self.assertEqual(self.post('trainings', {**FORM, 'title': 'No deck'})['gates'], 5)
        self.brand.brands = lambda: [{'brand': 'plain-co', 'name': 'Plain Co', 'variants': []}]
        self.engine.deck_needs(fresh=True)
        made = self.post('trainings', {**wanted, 'title': 'One look', 'brand': {
            'brand': 'plain-co', 'variant': None}})
        session = workspace.load(Path(made['path']))
        self.assertEqual((session['settings']['brand'], pipeline.brand_of(session)),
                         ('plain-co/', ('plain-co', None)))
        self.assertEqual(self.get('run', path=made['path'])['deck_left'], None)

    def test_the_run_shows_what_the_deck_says_and_the_deck_being_drawn(self):
        root = self.begin()
        self.to_outline(root)
        run = self.get('run', path=str(root))
        shown = run['outline']
        self.assertEqual(sorted(shown), ['checked', 'level', 'note', 'sha256', 'slides',
                                         'waiting', 'worth'])
        self.assertEqual((shown['level'], shown['waiting'], shown['note'], len(shown['slides']),
                          shown['checked']), (None, True, None, 6,
                                              list(pipeline.OUTLINE_CHECKED)))
        self.assertEqual(shown['slides'][2], {
            'id': 'when-capacity-holds', 'kind': 'content',
            'title': 'Capacity holds only with more than one instance', 'subtitle': None,
            'understand': 'A single instance has nothing to hold capacity while it restarts.',
            'points': [{'label': 'Several', 'text': 'The others carry the load.'},
                       {'label': 'One', 'text': 'Requests are dropped while it restarts.'}],
            'caveat': 'A single-instance app still drops requests while it restarts.',
            'source': None, 'notes': '7 min. Health checks start the next batch.',
            'serves': ['O2']})
        self.assertEqual(shown['worth'], [
            pipeline.IN_OTHER_WORDS, "The worker's own notes, which are its judgment and not "
            'a check: Six slides. The check slide is the one I am least sure of.'])
        self.assertEqual(run['deck'], {'level': None, 'sections': [], 'pictures': 0,
                                       'before': {'dollars': 2.4, 'minutes': 7.5}})
        item = self.get('trainings')['trainings'][0]
        self.assertEqual((item['state'], item['waiting']['artifact']), ('needs-you', None))
        self.assertEqual(self.get('trainings')['needs'], 1)

    def test_what_the_deck_says_is_decided_on_the_page(self):
        root = self.begin()
        seen = self.to_outline(root)['outline']['sha256']
        sent = {'path': str(root), 'level': None, 'decision': 'approve', 'note': None}
        self.assertIn('can be decided as: approve, revise',
                      self.post('outline', {**sent, 'decision': 'skip'}, 400)['error'])
        self.assertIn('Say what should change',
                      self.post('outline', {**sent, 'decision': 'revise'}, 400)['error'])
        self.assertIn('has changed since it was opened',
                      self.post('outline', {**sent, 'seen': 'f' * 64}, 409)['error'])
        self.assertEqual(self.post('outline', {**sent, 'path': str(self.base)}, 403)['error'],
                         'That folder is not a training this computer knows.')
        self.assertEqual(self.ask('POST', '/api/outline', sent, token=False)[0], 403)
        self.assertEqual(self.ask('GET', '/api/outline')[0], 405)
        run = self.post('outline', {**sent, 'seen': seen})
        self.assertEqual((run['state'], run['outline']['waiting'], run['deck']['pictures']),
                         ('waiting', False, 6))
        # A section's slides are numbered within its own preview, which is the number its
        # picture is asked for by, and each comes with its title.
        self.assertEqual(run['deck']['sections'], [
            {'id': 'section-1', 'state': 'done', 'previews': 1, 'slides': [1, 2],
             'titles': [OUTLINE['slides'][1]['title'], OUTLINE['slides'][2]['title']]},
            {'id': 'section-2', 'state': 'done', 'previews': 1, 'slides': [1, 2],
             'titles': [OUTLINE['slides'][3]['title'], OUTLINE['slides'][4]['title']]}])
        for section in run['deck']['sections']:
            for number in section['slides']:
                status, headers, body = self.ask('GET', '/api/slide?' + urlencode({
                    'path': str(root), 'section': section['id'], 'number': number}))
                self.assertEqual((status, body[:8]), (200, worker_tools.PNG), section)
        self.assertIn('is not waiting for a decision', self.post('outline', sent, 409)['error'])

    def test_the_decks_gate_shows_its_slides_the_review_the_audit_and_the_coverage(self):
        self.workers.found = [[SAID, SMALL]]
        root = self.begin()
        self.drawn(root)
        shown = self.get('gate', path=str(root), artifact='deck')
        self.assertEqual(shown['slides'][:2], [
            {'number': 1, 'id': 'cover-restarts', 'title': 'Rolling restarts'},
            {'number': 2, 'id': 'what-it-does',
             'title': 'A rolling restart replaces instances one batch at a time'}])
        self.assertEqual((len(shown['slides']), shown['review']['round'],
                          [finding['severity'] for finding in shown['review']['findings']]),
                         (6, 1, ['major', 'minor']))
        self.assertEqual(shown['audit'], {'status': 'warnings', 'blockers': [], 'warnings': [
            {'code': 'SMALL_TEXT', 'count': 2, 'says': 'Text under 18 points.'},
            {'code': 'HIGH_TEXT_DENSITY', 'count': 1, 'says': 'Many words for one slide.'}]})
        self.assertEqual(shown['coverage'], [
            {'objective': 'O1', 'says': 'Describe what a rolling restart does',
             'reviewed': [2], 'cited': [2, 5]},
            {'objective': 'O2', 'says': 'Explain when a rolling restart keeps capacity',
             'reviewed': [3], 'cited': [3, 5]},
            {'objective': 'O3', 'says': 'Handle the objection that rolling restarts guarantee '
             'zero downtime', 'reviewed': [4], 'cited': [4, 5]}])
        self.assertEqual(shown['sha256'], workspace.sha256_file(root / 'deck.pptx'))
        (root / 'deck.pptx').write_bytes(b'PK\x03\x04 another deck altogether')
        other = self.get('gate', path=str(root), artifact='deck')
        self.assertEqual((other['slides'], other['review'], other['audit'], other['coverage']),
                         ([], None, None, []), 'what was shown was of another deck')

    def test_the_audit_is_ok_when_nothing_was_raised_and_blocked_when_it_could_not_run(self):
        self.assertEqual(pipeline.audited({'status': 'PASS', 'warnings': [], 'blockers': []}),
                         {'status': 'ok', 'warnings': [], 'blockers': []})
        self.assertEqual(pipeline.audited({'status': 'x', 'blockers': [{'says': 'No logo.'}],
                                           'warnings': []})['status'], 'blocked')
        self.brand.refuse['audit'] = ['The deck could not be opened.']
        root = self.begin()
        self.drawn(root)
        self.assertEqual(self.gate(root)['audit'], {'status': 'blocked', 'warnings': [],
                         'blockers': ["The brand's audit could not be run. The brand skill "
                                      'refused: The deck could not be opened.']})

    def test_a_slides_picture_is_served_by_number_to_whoever_holds_the_key(self):
        root = self.begin()
        self.drawn(root)
        path = str(root)
        self.assertEqual(self.ask('GET', f'/api/slide?{urlencode({"path": path, "artifact": "deck", "number": 3})}'),
                         (200, 'image/png', png(3)))
        self.assertEqual(self.get('slide', path=path, section='section-2', number=2), png(2))
        self.assertEqual(self.ask('GET', f'/api/slide?{urlencode({"path": path, "artifact": "deck", "number": 3})}',
                                  token=False)[0], 403)
        self.assertEqual(self.ask('POST', '/api/slide', {'path': path})[0], 405)
        self.assertEqual(self.get('slide', 404, path=path, artifact='deck', number=7)['error'],
                         'There is no picture of that slide on this computer.')
        self.assertEqual(self.get('slide', 403, path=str(self.base), artifact='deck',
                                  number=1)['error'],
                         'That folder is not a training this computer knows.')

    def test_a_slides_address_can_never_be_made_to_read_another_file(self):
        root = self.begin()
        self.drawn(root)
        path = str(root)
        secret = root / 'work' / 'deck' / 'secret.png'
        secret.write_bytes(png(9))
        for params, status in (
                ({'artifact': 'deck', 'number': '../secret'}, 400),
                ({'artifact': 'deck', 'number': '1/../../secret'}, 400),
                ({'artifact': 'deck', 'number': '-1'}, 400),
                ({'artifact': 'deck', 'number': '0'}, 400),
                ({'artifact': 'deck', 'number': '１'}, 400),
                ({'artifact': 'deck', 'number': '1.png'}, 400),
                ({'artifact': 'blueprint', 'number': '1'}, 400),
                ({'artifact': '../deck', 'number': '1'}, 400),
                ({'artifact': 'deck@../..', 'number': '1'}, 400),
                ({'artifact': 'deck', 'section': 'section-1', 'number': '1'}, 400),
                ({'number': '1'}, 400),
                ({'section': '../preview', 'number': '1'}, 400),
                ({'section': 'section-1/../../preview', 'number': '1'}, 400),
                ({'section': 'section-9', 'number': '1'}, 404)):
            with self.subTest(params):
                reply = self.get('slide', status, path=path, **params)
                self.assertEqual(list(reply), ['error'])
        shots = root / 'work' / 'deck' / 'preview'
        (shots / '2.png').write_text('{"not": "a picture"}')
        self.assertEqual(self.get('slide', 400, path=path, artifact='deck', number=2)['error'],
                         'That picture cannot be shown.')
        (shots / '3.png').unlink()
        (shots / '3.png').symlink_to(self.base / 'gitconfig')
        self.assertEqual(self.get('slide', 404, path=path, artifact='deck', number=3)['error'],
                         'There is no picture of that slide on this computer.')
        outside = self.base / 'outside.png'
        outside.write_bytes(png(8))
        (shots / '4.png').unlink()
        (shots / '4.png').symlink_to(outside)
        self.get('slide', 404, path=path, artifact='deck', number=4)

    def test_the_check_of_this_computer_gains_what_a_deck_needs(self):
        looked = {'checked_at': 'now', 'ready': True, 'assistants': ['Claude Code'],
                  'wrong': [], 'items': [computer.item('node', 'Node', 'ok', [])]}
        root = self.begin()
        self.slides.have['drive'] = False
        with mock.patch.object(computer, 'check', lambda google=False: dict(looked)):
            found = self.post('computer', {})['computer']
        items = {item['id']: item for item in found['items']}
        self.assertEqual(list(items), ['node', 'deck-slides', 'deck-brand', 'deck-previews',
                                       'deck-pictures'])
        self.assertEqual(sorted(items['deck-previews']), sorted(items['node']))
        self.assertEqual((items['deck-slides']['state'], items['deck-slides']['facts'][0]),
                         ('ok', {'label': 'Installed', 'state': 'ok', 'detail': Slides.VERSION}))
        self.assertEqual((items['deck-previews']['state'], items['deck-previews']['fix'],
                          items['deck-previews']['optional']),
                         ('problem', engine_no_drive(), False))
        self.assertEqual((found['ready'], found['wrong']),
                         (False, ['A way to render previews of slides']))
        self.assertEqual(self.get('computer')['computer']['wrong'], found['wrong'])
        self.assertTrue(root.is_dir())


class BriefTests(JobCase):
    def test_a_decks_briefs_name_only_tools_their_workers_have(self):
        import re
        named = re.compile(r'`((?:list|read|submit|save|search|ask|check|preview|look)_[a-z_]+)`')
        expect = {'deck-outline': {'list_inputs', 'read_input', 'check_outline',
                                   'submit_outline', 'submit_review', 'ask_person'},
                  'deck-section': {'list_inputs', 'read_input', 'check_section',
                                   'preview_section', 'search_icons', 'submit_section'},
                  'deck-review': {'list_inputs', 'read_input', 'look_at_slide',
                                  'submit_assessment', 'submit_coverage'}}
        for job, tools in expect.items():
            with self.subTest(job):
                text = briefs.guidance(job)
                self.assertEqual(set(named.findall(text)), tools)
                closing = text.partition('\n## Hand back\n')[2]
                self.assertIn('fix them and hand it back again', closing)
                self.assertRegex(closing, r'\bstop\b')
                for avoided in (r'\b[\w-]+\.(?:md|json|py|mjs|txt|pptx|pdf)\b', r'\w/\w',
                                r'harness-|\bnode\b|\bpython|(?<![\w-])--[a-z]',
                                r'(?i)\bClaude\b|\bCodex\b|\bskill\b|\bMCP\b',
                                r'(?i)\b(artifacts?|stale|lineage)\b'):
                    self.assertEqual(re.findall(avoided, text), [], avoided)
        repair = briefs.guidance('deck-section', repair=True)
        self.assertLess(repair.index('## You are drawing this section again'),
                        repair.index('## Hand back'))
        self.assertIn('`look_at_slide`', repair)
        for told in ('the IDs of the blueprint objectives it serves',
                     'its title, its points, its caveat and its source line together',
                     'A cover carries a title and one subtitle line',
                     "Nothing under the blueprint's open gaps is on a slide",
                     'has a focal that is not one of them'):
            self.assertIn(told, briefs.guidance('deck-outline'))
        self.assertIn('`about`: `drawing`', briefs.guidance('deck-review'))

    def test_naming_rules_are_told_before_how_to_hand_back(self):
        for job, more in (('document', {}), ('brief', {'kind': 'product'}), ('scenario', {})):
            text = briefs.guidance(job, naming=True, **more)
            self.assertLess(text.index('## Names'), text.index('## Hand back'))
            self.assertIn('It governs names and nothing else', text)
            self.assertNotIn('## Names', briefs.guidance(job, **more))


if __name__ == '__main__':
    import unittest
    unittest.main()
