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
import runner_support
from runner_support import (BLUEPRINT, CHOSEN, NO_BRAND_SKILL, NO_SLIDES, OUTLINE, Brand,
                            JobCase, Slides, StudioCase, drawn, fails, left, png)

import computer
import desk
import workspace
from runner import brand as brand_skill
from runner import briefs, deck, page, pipeline, settings, worker_tools
from runner import slides as slides_tool
from stand_ins import slides as slides_stand_in
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


def approved_plan() -> dict:
    """The plan the slides tool keeps once the design of OUTLINE is proposed, as `design
    check` gives it back: the third slide keeps the limit its caveat states, and the fourth
    shows the same instance icon as the second, already found."""
    from stand_ins import design as designs
    plan = designs.validate(deck.proposal(OUTLINE, runner_support.designed(OUTLINE)))
    plan['slides'][2]['qualifications'] = ['still drops requests']
    plan['slides'][3]['asset']['candidates'] = [{
        'assetId': 'icon_instance', 'kind': 'icon', 'ref': 'server', 'concept': 'An instance',
        'status': 'resolved'}]
    return designs.validate(plan)


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

    def test_a_deck_drawn_from_its_design_draws_its_visuals_and_keeps_the_relevance_rules(self):
        self.assertIn('An icon is optional', deck.HOUSE[-1], 'a deck without a design as before')
        self.assertEqual(deck.DESIGNED_HOUSE[:-1], deck.HOUSE[:-1])
        for told in ('Draw what the approved design says', 'names a recognisable thing',
                     'the same icon for the same concept across the deck',
                     'never twice on one slide'):
            self.assertIn(told, deck.DESIGNED_HOUSE[-1])
        self.assertNotIn('optional', ' '.join(deck.DESIGNED_HOUSE))
        self.assertEqual(deck.complete(OUTLINE, Slides.LAYOUTS, [])['house'], list(deck.HOUSE))
        self.assertEqual(deck.complete(OUTLINE, Slides.LAYOUTS, [], designed=True)['house'],
                         list(deck.DESIGNED_HOUSE))

    def test_a_sections_brief_carries_its_approved_design_and_the_icons_across_the_deck(self):
        plan = approved_plan()
        whole = deck.complete(OUTLINE, Slides.LAYOUTS, [], designed=True)
        written = Slides._brief(whole, 1, whole['slides'][1:3], '/opt/brand/contract.json',
                                Path('/opt/work'))
        given = deck.brief(written, whole, design=plan)
        steps = plan['slides'][1]
        for told in ('## The approved design', '### `what-it-does`',
                     '### `when-capacity-holds`', f"- Claim: {OUTLINE['slides'][1]['title']}",
                     '- Relationship: order',
                     '- Visual: diagram. Its purpose: Show the points as the parts of one '
                     'mechanism.', '- How it is drawn: Native boxes for each point',
                     '- Why: The parts and how they connect are spatial',
                     '- Weighed against: A list of the points. A list hides how the parts '
                     'connect.', '- Asset: Native boxes and connectors. (selected: The boxes '
                     'carry the relation.)', '  - icon "server" for An instance, still to be '
                     'found', '- Wording it must keep: "still drops requests"',
                     '```json\n' + json.dumps(steps['intent'], ensure_ascii=False) + '\n```',
                     'is direct text by decision', 'Only icons can be placed in this version',
                     '"id", "title", "sources", "intent", "brief"',
                     "Copy each slide's `id`, `title`, `sources`, `intent`, caveat",
                     f'- {deck.DESIGNED_HOUSE[-1]}', '## Icons across the deck',
                     '- An instance: "server", on `what-it-does`, `the-objection`'):
            self.assertIn(told, given)
        self.assertNotIn('### `the-objection`', given, 'only its own slides are described')
        self.assertNotIn(deck.HOUSE[-1], given)
        self.assertEqual(deck.icons(plan), [{'concept': 'An instance', 'ref': 'server',
                                             'status': 'resolved', 'slides': [
                                                 'what-it-does', 'the-objection']}])
        none = json.loads(json.dumps(plan))
        for slide in none['slides']:
            slide['asset'].pop('candidates', None)
        self.assertIn('The approved design names no icon.', deck.brief(written, whole,
                                                                       design=none))
        # A deck without a design is briefed as it always was.
        plain = deck.complete(OUTLINE, Slides.LAYOUTS, [])
        before = deck.brief(Slides._brief(plain, 1, plain['slides'][1:3],
                                          '/opt/brand/contract.json', Path('/opt/work')), plain)
        for gone in ('## The approved design', '## Icons across the deck', '`intent`'):
            self.assertNotIn(gone, before)
        self.assertIn(f'- {deck.HOUSE[-1]}', before)

    def test_a_section_drawn_from_its_design_keeps_its_intent_and_the_approved_copy(self):
        plan = approved_plan()
        whole = deck.complete(OUTLINE, Slides.LAYOUTS, [], designed=True)
        spec = deck.fixed(whole, ['what-it-does', 'when-capacity-holds'], 1, plan)
        first, second = spec['slides']
        self.assertEqual((json.loads(first['intent']), second['qualifications']),
                         (plan['slides'][1]['intent'], ['still drops requests']))
        self.assertEqual(list(json.loads(first['intent'])), list(plan['slides'][1]['intent']),
                         'kept as text, the intent keeps the order of its keys')
        good = drawn(spec)
        self.assertEqual(deck.kept(good, spec), [])
        for change, expect in (
                (lambda made: made['slides'][0].pop('intent'),
                 'what-it-does: `intent` is copied exactly as it was approved.'),
                (lambda made: made['slides'][0]['intent']['visual'].update(family='text'),
                 'what-it-does: `intent` is copied exactly as it was approved.'),
                (lambda made: made['slides'][1].pop('caveat'),
                 'when-capacity-holds: the approved design keeps this wording, which is '
                 'missing or changed: "still drops requests"')):
            made = json.loads(json.dumps(good))
            change(made)
            self.assertIn(expect, ' '.join(deck.kept(made, spec)))
        # The words are held to the copy the person approved with the design.
        approved = json.loads(json.dumps(plan))
        approved['slides'][1]['copy']['points'][0]['text'] = 'Instances restart in batches.'
        self.assertEqual(deck.kept(good, deck.fixed(whole, ['what-it-does',
                                                            'when-capacity-holds'], 1,
                                                    approved)),
                         ['what-it-does: these approved words are missing or changed: '
                          '"Instances restart in batches."'])
        # An intent with its keys in another order is the approved one, written as approved.
        shuffled = json.loads(json.dumps(good))
        shuffled['slides'][0]['intent'] = json.loads(json.dumps(
            shuffled['slides'][0]['intent'], sort_keys=True))
        self.assertEqual(deck.kept(shuffled, spec), [])
        self.assertNotEqual(list(shuffled['slides'][0]['intent']),
                            list(plan['slides'][1]['intent']))
        self.assertEqual(list(deck.as_approved(shuffled, spec)['slides'][0]['intent']),
                         list(plan['slides'][1]['intent']))
        # Without a design, nothing new is fixed or checked.
        plain = deck.fixed(deck.complete(OUTLINE, Slides.LAYOUTS, []),
                           ['what-it-does', 'when-capacity-holds'], 1)
        self.assertEqual(sorted(plain['slides'][0]), ['caveat', 'id', 'notes', 'points',
                                                      'source', 'sources', 'title'])
        self.assertIs(deck.as_approved(good, plain), good)

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

    def test_a_design_is_handed_in_with_its_outline_and_checked_by_the_rules_and_the_tool(self):
        tools = self.tools(artifacts={'outline': {'kind': 'outline', 'brand': self.contract,
                                                  'blueprint': BLUEPRINT, 'design': True}})
        self.assertEqual(self.offered(tools), [
            'list_inputs', 'read_input', 'submit_review', 'check_outline', 'submit_outline',
            'ask_person'], 'the same tools, and none that approves')
        good = runner_support.designed(OUTLINE)
        self.assertIn('Hand the outline in with its design',
                      self.refused(tools.check_outline(json.dumps(OUTLINE))))
        self.assertEqual(self.ok(tools.check_outline(json.dumps(OUTLINE), json.dumps(good))),
                         'Nothing to put right. Hand it in with submit_outline.')
        short = {'slides': good['slides'][:-1]}
        self.assertIn('one entry for every slide of the outline, the cover, section and '
                      'closing slides too, in its order: cover-restarts, what-it-does',
                      self.ok(tools.check_outline(OUTLINE, short)))
        copied = runner_support.designed(OUTLINE)
        copied['slides'][1]['title'] = 'Another title'
        self.assertIn('what-it-does: leave out `title`. The title, the copy, the notes and the '
                      'objectives are taken from the outline.',
                      self.ok(tools.check_outline(OUTLINE, copied)))
        # What the tool will not take comes back slide by slide, with its way out.
        kept = runner_support.designed(OUTLINE)
        kept['slides'][2]['qualifications'] = ['drops every request']
        unresolved = runner_support.designed(OUTLINE)
        unresolved['slides'][3]['intent']['visual']['family'] = 'icon'
        unresolved['slides'][3]['asset']['disposition'] = 'unavailable'
        said = self.ok(tools.check_outline(OUTLINE, kept))
        self.assertIn('- when-capacity-holds: the qualification "drops every request" does not '
                      'appear in the slide copy', said)
        said = self.ok(tools.check_outline(OUTLINE, unresolved))
        self.assertIn('- the-objection: An unresolved asset cannot be the selected visual; '
                      'propose an explicit fallback for approval. Instead, you may propose this, '
                      'which the person approves like the rest: A native diagram', said)
        self.assertEqual(list((self.job / 'drafts').glob('design-*')), [],
                         'each check proposes in a project of its own, thrown away after')
        self.assertEqual(self.ok(tools.submit_outline(OUTLINE, good)), 'Accepted: outline.')
        handed = worker_tools.collect(self.job)['artifacts']['outline']
        kept = json.loads(handed['text'])
        self.assertEqual((kept['outline'], kept['design']),
                         (OUTLINE, deck.proposal(OUTLINE, good)))
        self.assertEqual([(outcome['check'], outcome['status']) for outcome in handed['checks']],
                         [('outline.tool', 'passed'), ('outline.rules', 'passed'),
                          ('outline.design', 'passed')])
        self.job = self.base / 'words-alone'
        plain = self.writer()
        self.assertIn('handed in without a design',
                      self.refused(plain.check_outline(OUTLINE, good)))

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

    def test_a_section_drawn_from_its_design_is_checked_and_previewed_against_it(self):
        project = self.base / 'deck'
        project.mkdir()
        proposal = self.base / 'proposal.json'
        proposal.write_text(json.dumps(deck.proposal(OUTLINE, runner_support.designed(OUTLINE))))
        asked = self.slides.design_propose(project, proposal)
        self.slides.design_respond(project, {
            'questionId': asked['question']['id'], 'planRevision': asked['revision'],
            'decision': 'approve', 'feedback': 'Approve the whole plan'})
        plan = self.slides.design_check(project)['plan']
        whole = deck.complete(OUTLINE, Slides.LAYOUTS, [], designed=True)
        self.spec = {**self.spec, **deck.fixed(whole, ['what-it-does', 'when-capacity-holds'],
                                               1, plan), 'design': str(project), 'section': True}
        tools, good = self.composer(), drawn(self.spec)
        good['slides'][0]['intent'] = json.loads(json.dumps(good['slides'][0]['intent'],
                                                            sort_keys=True))
        self.assertTrue(self.ok(tools.check_section(json.dumps(good))).startswith(
            'Nothing to put right.'))
        self.assertEqual(self.slides.calls[-1][-2:], (str(project), 'section=True'))
        sent = json.loads(Path(self.slides.calls[-1][1]).read_text())
        self.assertEqual(list(sent['slides'][0]['intent']), list(plan['slides'][1]['intent']),
                         'the tool is sent the intent as it was approved')
        self.ok(tools.preview_section(json.dumps(good)))
        self.assertIn(('preview_design', self.slides.calls[-1][1], str(project), 'section=True'),
                      self.slides.calls)
        self.ok(tools.submit_section(json.dumps(good)))
        # What the tool refuses against the design is given to the composer, slide by slide.
        changed = json.loads(proposal.read_text())
        changed['slides'][1]['composition'] = 'Three boxes in a column.'
        proposal.write_text(json.dumps(changed))
        self.slides.design_propose(project, proposal, asked['revision'])
        said = self.ok(tools.check_section(json.dumps(good)))
        self.assertIn('- Awaiting design approval; show the proposed slide(s)', said)

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


class AssetToolTests(ToolCase):
    """A composer whose deck's slides tool keeps its assets: it lists them, records a brand
    icon, and asks the tool's own image provider for the generated art of its own slides."""

    def setUp(self):
        super().setUp()
        self.slides.design = self.slides.keeps = True
        self.project = self.base / 'deck'
        self.project.mkdir()
        proposal = self.base / 'proposal.json'
        proposal.write_text(json.dumps(deck.proposal(OUTLINE, with_assets(
            runner_support.designed(OUTLINE), generated=True))))
        asked = self.slides.design_propose(self.project, proposal)
        self.slides.design_respond(self.project, {
            'questionId': asked['question']['id'], 'planRevision': asked['revision'],
            'decision': 'approve', 'feedback': 'Approve the whole plan'})
        plan = self.slides.design_check(self.project)['plan']
        self.slides.asset_icon(self.project, 'icon-server', 'icon_instance', None,
                               self.contract)
        picture = self.base / 'console.png'
        picture.write_bytes(png(3))
        self.slides.asset_supplied(self.project, picture, 'console_view', 'The console',
                                   'Course author', 'screenshot', 'Internal only')
        whole = deck.complete(OUTLINE, Slides.LAYOUTS, [], designed=True)
        self.spec = {**self.spec, **deck.fixed(whole, ['what-it-does', 'when-capacity-holds'],
                                               1, plan), 'design': str(self.project),
                     'section': True, 'assets': {
                         'project': str(self.project),
                         'generated': {'capacity_art': 'when-capacity-holds'}}}

    def test_a_composer_lists_what_is_recorded_and_never_a_folder(self):
        tools = self.composer()
        self.assertEqual(self.offered(tools), [
            'list_inputs', 'read_input', 'check_section', 'preview_section', 'search_icons',
            'list_assets', 'request_asset', 'submit_section'])
        said = self.ok(tools.list_assets())
        for told in ('- `icon_instance`: the icon `icon-server` (Server). Place it as an icon '
                     'node with that icon ID.',
                     '- `console_view`: a screenshot picture of The console. Source: Course '
                     'author. Use it only so: Internal only. Place it by its asset ID.',
                     '- `capacity_art`: generated art for `when-capacity-holds`, not made yet.'):
            self.assertIn(told, said)
        self.assertNotIn(str(self.base), said)
        # A recorded picture is placed by its ID, and one not recorded is the tool's to refuse.
        shot = {'type': 'image', 'id': 's1_console', 'asset': 'console_view'}
        good = drawn(self.spec, placing={'what-it-does': [shot]})
        self.assertTrue(self.ok(tools.check_section(json.dumps(good))).startswith(
            'Nothing to put right.'))
        wrong = drawn(self.spec, placing={'what-it-does': [{**shot, 'asset': 'nowhere'}]})
        self.assertIn("asset nowhere is not in the project's asset manifest",
                      self.ok(tools.check_section(json.dumps(wrong))))

    def test_generated_art_is_asked_of_the_tools_own_provider_for_its_own_slides_alone(self):
        tools, brief = self.composer(), 'Two instances side by side, one restarting.'
        said = self.refused(tools.request_asset('capacity_art', slide='when-capacity-holds',
                                                prompt=brief))
        for told in ('The image provider (gemini-api) is not ready.', 'GEMINI_API_KEY',
                     'say what is missing when you hand in'):
            self.assertIn(told, said)
        self.assertIn('Only the generated art the approved design names for your own slides',
                      self.refused(tools.request_asset('console_view', prompt=brief)))
        self.assertIn('not of `what-it-does`', self.refused(tools.request_asset(
            'capacity_art', slide='what-it-does', prompt=brief)))
        self.assertIn('Ask for one thing', self.refused(tools.request_asset(
            'capacity_art', icon='icon-clock', prompt=brief)))
        self.slides.env = {'GEMINI_API_KEY': 'set'}   # the stub stands for the provider
        self.assertIn('`capacity_art` is made and recorded', self.ok(tools.request_asset(
            'capacity_art', prompt=brief, alt='Two instances')))
        entry = json.loads((self.project / '.harness-slides' / 'assets.json').read_text())
        art = next(item for item in entry['assets'] if item['assetId'] == 'capacity_art')
        self.assertEqual((art['kind'], art['provenance']['slide'], art['alt']),
                         ('generated', 'when-capacity-holds', 'Two instances'))
        self.assertIn(f'have asked for {worker_tools.GENERATIONS} pictures', self.refused(
            tools.request_asset('capacity_art', prompt=brief)))

    def test_a_brand_icon_is_recorded_by_its_library_id(self):
        tools = self.composer()
        self.assertEqual(self.ok(tools.request_asset('icon_clock', icon='icon-clock')),
                         '`icon_clock` is the icon `icon-clock` (Clock). Place it as an icon '
                         'node with that icon ID.')
        self.assertIn('unknown icon icon-nowhere', self.refused(tools.request_asset(
            'icon_other', icon='icon-nowhere')))
        self.assertIn('already recorded', self.refused(tools.request_asset(
            'icon_instance', icon='icon-clock')))
        self.assertIn('An icon is named by the ID', self.refused(tools.request_asset(
            'icon_x', icon='a/b')))


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


class JudgingToolTests(ToolCase):
    """A reviewer of a deck reviewed against its approved design: it answers the slides
    tool's own criteria, and the tool checks the answer against the review it prepared."""

    def reviewer(self) -> worker_tools.WorkerTools:
        self.slides.design = self.slides.judges = True
        self.slides.have['local'] = True
        project, build = self.base / 'deck', self.base / 'whole'
        project.mkdir()
        build.mkdir()
        plan = deck.proposal(OUTLINE, runner_support.designed(OUTLINE))
        (build / 'proposal.json').write_text(json.dumps(plan))
        asked = self.slides.design_propose(project, build / 'proposal.json')
        self.slides.design_respond(project, {
            'questionId': asked['question']['id'], 'planRevision': asked['revision'],
            'decision': 'approve', 'feedback': 'Approve the whole plan'})
        (build / 'composition.json').write_text(json.dumps({'title': OUTLINE['title'], 'slides': [
            {'id': slide['id'], 'title': slide['title'], 'sources': slide['sources'],
             'intent': slide['intent'], 'canvas': {'type': 'stack', 'children': [
                 {'type': 'text', 'id': f"x{number}_words", 'text': slide['title']}]}}
            for number, slide in enumerate(plan['slides'], 1)]}))
        self.slides.compile(build / 'composition.json', self.contract, build / 'compiled',
                            design=project)
        output = build / 'review'
        made = self.slides.review_prepare(build / 'compiled', output, project)
        record = json.loads((output / 'review.json').read_text())
        self.packets = [self.slides.review_slide(output, slide['id'])
                        for slide in plan['slides']]
        slides = [{'number': page['number'], 'id': slide['id'], 'title': slide['title'],
                   'image': str(output / page['image'])}
                  for page, slide in zip(record['slides'], plan['slides'])]
        self.output, self.made = output, made
        return self.tools(inputs={'the review': 'The criteria.'}, ask=False, review={
            'preview': str(output), 'deck': record['source']['sha256'], 'slides': slides,
            'objectives': ['O1', 'O2', 'O3'], 'recorded': str(build / 'assessment.json'),
            'judged': {'output': str(output), 'revision': made['revision'],
                       'binding': made['assessmentBinding'], 'packets': self.packets}})

    def looked(self) -> worker_tools.WorkerTools:
        tools = self.reviewer()
        for number in range(1, 7):
            self.ok(tools.look_at_slide(number))
        return tools

    def test_a_reviewer_answers_the_tools_criteria_and_has_no_other_way_to_hand_in(self):
        tools = self.reviewer()
        self.assertEqual(self.offered(tools), ['list_inputs', 'read_input', 'look_at_slide',
                                               'submit_judgements', 'submit_coverage'])
        self.assertIn('submit_judgements', self.refused(tools.submit_assessment([])))
        self.assertEqual(self.refused(tools.submit_judgements([])), 'Look at every slide '
                         'first. Not looked at yet: 1, 2, 3, 4, 5, 6.')

    def test_an_answer_that_is_not_whole_goes_back_to_the_reviewer(self):
        tools = self.looked()
        given = runner_support.judgements(self.packets)
        given[1]['checks'] = given[1]['checks'][1:]
        given[2]['checks'][0]['objects'] = ['nowhere']
        given[3]['checks'][0].update(status='issue')
        said = self.refused(tools.submit_judgements(given, ['nowhere']))
        for told in ('what-it-does: answer each of these criteria once: title-support, ',
                     "when-capacity-holds, `title-support`: `objects` names what you judged, "
                     "from this slide's objects:",
                     'the-objection, `title-support`: `severity` is one of: critical, major, '
                     'minor.', 'the-objection, `title-support`: `about` is one of: drawing, '
                     'content, concept.', 'weakest names up to three slides'):
            self.assertIn(told, said)
        self.assertEqual(self.slides.assessed, [], 'nothing reached the slides tool')

    def test_what_the_slides_tool_refuses_in_an_answer_goes_back_to_the_reviewer(self):
        tools = self.looked()
        given = runner_support.judgements(self.packets)
        for entry in given[1:3]:
            next(check for check in entry['checks']
                 if check['criterion'] == 'explanatory-value')['reason'] = 'Fine as drawn here.'
        self.assertIn('- Use slide-specific evidence for explanatory-value; a duplicated bulk '
                      'approval is insufficient', self.refused(tools.submit_judgements(given)))
        self.assertIsNone(worker_tools.collect(self.job)['assessment'])

    def test_an_answer_is_recorded_against_the_review_with_what_is_unresolved(self):
        tools = self.looked()
        issue = {'slide': 'what-it-does', 'criterion': 'visual-relationship',
                 'severity': 'major', 'about': 'drawing',
                 'reason': 'The steps are stacked with nothing joining them.'}
        said = self.ok(tools.submit_judgements(json.dumps(runner_support.judgements(
            self.packets, [issue])), ['what-it-does']))
        self.assertEqual(said, 'Recorded: 1 judgement left unresolved. Now say which slides '
                               'address each objective, with submit_coverage.')
        record = json.loads((self.output / 'review.json').read_text())
        self.assertEqual((record['pending'], record['slides'][0]['finalReview']['note']),
                         ([], deck.MARKED))
        assessed = self.slides.assessed[-1]
        self.assertEqual({key: assessed[key] for key in ('schema', 'sceneDigest',
                                                         'qualityRevision', 'artifactDigest')},
                         self.made['assessmentBinding'])
        self.assertEqual(assessed['slides'][1]['checks'][0]['sources'], ['O1'])
        kept = worker_tools.collect(self.job)['assessment']
        self.assertEqual(kept['findings'], [{
            'slide': 'what-it-does', 'number': 2, 'criterion': 'visual-relationship',
            'category': 'visual-teaching', 'severity': 'major', 'about': 'drawing',
            'note': issue['reason'], 'fix': None}])
        self.assertEqual((kept['weakest'], kept['complete']), (['what-it-does'], False))
        self.assertEqual([(entry['slide'], entry['accepted']) for entry in kept['direct']],
                         [('cover-restarts', True), ('closing-practice', True)])


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
        # The sections are drawn side by side, so the other one may not have used all its
        # failures before the training stopped. Whatever is left must not fail the retry.
        self.workers.queued.pop('section', None)
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


class DesignTests(DeckCase):
    """A slides tool with a design session: what a deck says is proposed with how each slide
    is drawn, the person's one decision is the tool's answer, and the sections are drawn
    from and built against what was approved. Rows V01, V02, V03, V04, V13 and V14 of the
    state-transition matrix in docs/superpowers/plans/2026-10-14-visual-teaching-in-decks.md."""

    def setUp(self):
        super().setUp()
        self.slides.design = True

    def session(self, root: Path, level: str | None = None) -> dict:
        """What the slides tool holds of a deck's design, read as it says it."""
        return self.slides.design_status(pipeline.place(root, level, pipeline.DESIGNS))

    def proposal(self, root: Path) -> dict:
        return json.loads((root / pipeline.DESIGN).read_text())

    def test_the_outline_job_hands_in_a_design_and_the_runner_makes_the_proposal(self):
        root = self.begin()
        view = self.to_outline(root)
        job, spec = [(job, spec) for kind, job, spec in self.workers.jobs if kind == 'outline'][-1]
        self.assertEqual(job.guidance, briefs.guidance('deck-outline', design=True))
        self.assertIn('design guidance', [entry['name'] for entry in spec['inputs']])
        self.assertIn('Hand the outline in with its design, together', job.task)
        self.assertTrue(spec['artifacts']['outline']['design'])
        made = self.proposal(root)
        self.assertEqual((made['schema'], made['scope'],
                          [slide['id'] for slide in made['slides']]),
                         (2, 'new', [slide['id'] for slide in OUTLINE['slides']]))
        cover, steps, closing = made['slides'][0], made['slides'][1], made['slides'][-1]
        self.assertEqual((cover['copy'], cover['sources'], cover['intent']['evidence']),
                         ({'points': [], 'focal': OUTLINE['slides'][0]['subtitle']},
                          ['outline'], ['outline']))
        self.assertEqual(closing['copy'], {'points': [], 'focal': OUTLINE['slides'][-1]['title']})
        self.assertEqual(steps['copy'], {'points': OUTLINE['slides'][1]['points'],
                                         'focal': 'One batch at a time',
                                         'source': 'Platform documentation: restarts'})
        self.assertEqual((steps['objectives'], steps['sources'], steps['notes']),
                         (['O1'], ['O1'], OUTLINE['slides'][1]['notes']))
        self.assertNotIn('understand', json.dumps(steps), 'a requirement, not copy')
        self.assertEqual(json.loads((root / pipeline.OUTLINE).read_text()), OUTLINE)
        drafted = self.record(root)['deck']['']['outline']
        self.assertEqual(drafted['design'], workspace.sha256_file(root / pipeline.DESIGN))
        self.assertIn(pipeline.DESIGN_CHECKED, view['outline']['checked'])

    def test_visual_01_approval_binds_copy_and_design(self):
        root = self.begin()
        view = self.to_outline(root)
        shown = view['outline']
        revision = self.session(root)['revision']
        self.assertEqual(shown['design'], {'revision': revision, 'asked': [
            slide['id'] for slide in OUTLINE['slides']]})
        question = self.session(root)['question']
        self.assertEqual(question['options'], ['Approve the whole plan', 'Request changes'])
        self.assertEqual(self.slides.replies, [], 'nothing is answered before the person')
        self.engine.outline(root, None, 'approve', seen=shown['sha256'], design=revision)
        # One decision, one answer: the option chosen, word for word, as no note was given.
        self.assertEqual(self.slides.replies, [{
            'questionId': question['id'], 'planRevision': revision, 'decision': 'approve',
            'feedback': 'Approve the whole plan'}])
        approved = self.record(root)['deck']['']['approved']
        self.assertEqual((approved['sha256'], approved['design'], approved['by']), (
            shown['sha256'], {'sha256': workspace.sha256_file(root / pipeline.DESIGN),
                              'revision': revision}, 'page'))
        self.assertEqual((self.session(root)['buildAllowed'], self.session(root)['pending']),
                         (True, []))
        # Construction became eligible, and was started against the approval.
        names = [call[0] for call in self.slides.calls]
        self.assertLess(names.index('design_check'), names.index('outline_start'))
        self.assertEqual(self.built(root)['start']['design'], approved['design'])
        self.assertEqual(workspace.status(root)['gate'], 'deck')
        # The tool's record of the approval is shared with the outline it binds.
        tracked = self.git('ls-files', 'trainings/rolling-restarts').splitlines()
        for kept in ('deck/outline.json', 'deck/design.json',
                     'deck/.harness-slides/design/session.json'):
            self.assertIn(f'trainings/rolling-restarts/{kept}', tracked)
        self.assertEqual(self.git('status', '--porcelain'), '')

    def compiled(self) -> list[tuple]:
        """Every compile and preview the deck asked of the tool against a design, as
        (call, section or not)."""
        return [(call[0], call[-1]) for call in self.slides.calls
                if call[0] in ('compile', 'preview_design') and call[-1].startswith('section=')]

    def test_sections_are_drawn_from_the_approved_design_and_built_against_it(self):
        root = self.begin()
        self.drawn(root)
        plan = self.slides.design_check(root / pipeline.DESIGNS)['plan']
        start = next((root / 'work' / 'deck').glob('start-*'))
        kept = json.loads((start / pipeline.APPROVED_DESIGN).read_text())
        self.assertEqual((kept, list(kept['slides'][1]['intent'])),
                         (plan, list(plan['slides'][1]['intent'])))
        self.assertEqual(json.loads((start / 'given' / 'outline.json').read_text())['house'],
                         list(deck.DESIGNED_HOUSE))
        sections = [(job, spec) for kind, job, spec in self.workers.jobs if kind == 'section']
        self.assertEqual(len(sections), 2)
        # The sections are drawn side by side, so they are told apart by what they hold.
        approved = {slide['id']: slide['intent'] for slide in plan['slides']}
        for job, spec in sections:
            made = spec['artifacts']['section']
            self.assertEqual(job.guidance, briefs.guidance('deck-section', design=True))
            self.assertEqual((made['design'], made['section']),
                             (str(root / pipeline.DESIGNS), True))
            self.assertEqual({slide['id']: json.loads(slide['intent'])
                              for slide in made['slides']},
                             {slide['id']: approved[slide['id']] for slide in made['slides']})
        self.assertEqual(sorted(slide['id'] for _, spec in sections
                                for slide in spec['artifacts']['section']['slides']),
                         sorted(slide['id'] for slide in OUTLINE['slides']
                                if slide['kind'] == 'content'))
        brief = (start / 'given' / 'section-1.md').read_text()
        for told in ('## The approved design', '### `what-it-does`', '## Icons across the deck',
                     '- An instance: "server", on `what-it-does`', deck.DESIGNED_HOUSE[-1]):
            self.assertIn(told, brief)
        self.assertNotIn(str(self.base), brief)
        # Each section is checked and previewed as a section; the whole deck as the deck.
        built = self.compiled()
        self.assertEqual(built[-2:], [('compile', 'section=False'),
                                      ('preview_design', 'section=False')])
        self.assertEqual({call for call in built[:-2]},
                         {('compile', 'section=True'), ('preview_design', 'section=True')})
        self.assertEqual((len(self.slides.replies), workspace.status(root)['gate']),
                         (1, 'deck'), 'one decision, and nothing asked of the person since')

    def test_visual_04_fit_repair_preserves_design(self):
        self.workers.found = [[MAJOR]]
        root = self.begin()
        self.drawn(root)
        approved = self.record(root)['deck']['']['approved']
        self.assertEqual(self.kinds()[-6:], ['outline', 'section', 'section', 'review',
                                             'section', 'review'])
        job, spec = [(job, spec) for kind, job, spec in self.workers.jobs
                     if kind == 'section'][-1]
        self.assertEqual(job.guidance, briefs.guidance('deck-section', repair=True,
                                                       design=True))
        self.assertTrue(spec['artifacts']['section']['design'])
        # The approval holds: nothing was asked of the person or the tool again.
        status = self.session(root)
        self.assertEqual((len(self.slides.replies), status['revision'], status['pending'],
                          status['buildAllowed']),
                         (1, approved['design']['revision'], [], True))
        self.assertEqual(self.record(root)['deck']['']['approved'], approved)
        self.assertEqual(self.built(root)['start']['design'], approved['design'])
        # The section drawn again was built against it, and the deck rendered and reviewed again.
        rounds = self.built(root)['rounds']
        self.assertEqual((len(rounds), [bool(made['review']) for made in rounds]),
                         (2, [True, True]))
        self.assertNotEqual(rounds[0]['made_from'], rounds[1]['made_from'])
        self.assertNotEqual(rounds[0]['folder'], rounds[1]['folder'])
        self.assertEqual(self.compiled()[-6:], [
            ('compile', 'section=True'), ('compile', 'section=True'),
            ('preview_design', 'section=True'), ('compile', 'section=True'),
            ('compile', 'section=False'), ('preview_design', 'section=False')])
        self.assertEqual(workspace.status(root)['gate'], 'deck')

    def test_visual_14_sections_need_a_tool_that_checks_them_against_the_design(self):
        self.slides.gate = False
        root = self.begin()
        shown = self.to_outline(root)['outline']
        view = self.engine.outline(root, None, 'approve', seen=shown['sha256'],
                                   design=shown['design']['revision'])
        self.assertEqual(view['state'], 'stopped')
        self.assertIn('cannot check a section against it. Update harness-slides',
                      view['problem']['what'])
        approved = self.record(root)['deck']['']['approved']
        self.assertEqual(approved['design']['revision'], shown['design']['revision'])
        self.assertEqual(([call[0] for call in self.slides.calls].count('outline_start'),
                          self.kinds().count('section')), (0, 0), 'nothing is started')
        self.slides.gate = True
        view = self.engine.act(root, 'retry')
        self.assertEqual((view['state'], workspace.status(root)['gate']), ('waiting', 'deck'))
        self.assertEqual(self.record(root)['deck']['']['approved'], approved)
        self.assertEqual(len(self.slides.replies), 1, 'the approval was not asked for again')

    def test_a_start_that_did_not_keep_the_approved_design_is_made_again(self):
        self.workers.then('section', *[fails()] * 6)
        root = self.begin()
        self.assertEqual(self.drawn(root)['state'], 'failed')
        found = self.engine._survey(root, self.record(root)).decks[None]
        self.assertIn('deck-start', found.done)
        start = next((root / 'work' / 'deck').glob('start-*'))
        (start / pipeline.APPROVED_DESIGN).unlink()
        found = self.engine._survey(root, self.record(root)).decks[None]
        self.assertNotIn('deck-start', found.done)

    def test_visual_02_worker_cannot_approve(self):
        root = self.begin()
        self.to_outline(root)
        tools = worker_tools.WorkerTools  # every tool any worker can be offered
        self.assertEqual([name for name in worker_tools.NAMES
                          if 'respond' in name or 'approve' in name or 'design' in name], [])
        self.assertFalse(hasattr(tools, 'design_respond'))
        for _ in range(3):
            self.engine.wake(root)
            self.engine.resume()
        self.assertEqual((self.slides.replies, self.kinds().count('section')), ([], 0))
        self.assertNotIn('approved', self.record(root)['deck'][''])
        self.assertEqual((self.session(root)['buildAllowed'], len(self.session(root)['pending'])),
                         (False, 6))
        # A worker's design that carries anything of the person's is refused before the tool.
        sneaky = runner_support.designed(OUTLINE)
        sneaky['slides'][0]['approved'] = True
        self.assertEqual(deck.design_rules(OUTLINE, sneaky), [
            'cover-restarts: leave out `approved`. The title, the copy, the notes and the '
            'objectives are taken from the outline.'])
        self.assertEqual(deck.design_rules(OUTLINE, {**sneaky, 'decision': 'approve'})[0],
                         'Leave out `decision`: the design holds its slides and nothing else.')

    def test_visual_03_design_change_requires_review(self):
        root = self.begin()
        self.drawn(root)
        first = self.session(root)['revision']
        self.assertEqual((workspace.status(root)['gate'], self.kinds().count('section')),
                         ('deck', 2))
        changed = runner_support.designed(OUTLINE)
        changed['slides'][3]['intent']['visual'] = {
            'family': 'regions', 'purpose': 'Set the claim and its correction apart.'}
        self.workers.design_said = changed
        self.decide(root, 'deck', 'revise', 'Show the claim and the correction apart.')
        view = self.view(root)
        self.assertEqual((view['outline']['waiting'], view['outline']['design']['asked']),
                         (True, ['the-objection']), 'only the changed slide is asked about')
        status = self.session(root)
        self.assertEqual((status['buildAllowed'], status['pending']), (False, ['the-objection']))
        self.assertNotEqual(status['revision'], first)
        self.assertNotIn('deck-start', self.engine._survey(root, self.record(root))
                         .decks[None].done, 'the start was made from the earlier design')
        with self.assertRaises(slides_tool.Refused):
            self.slides.design_check(root / pipeline.DESIGNS)
        self.assertEqual(self.kinds().count('section'), 2, 'nothing is drawn meanwhile')
        self.engine.outline(root, None, 'approve', design=status['revision'])
        self.assertEqual(self.slides.replies[-1]['feedback'], 'Approve these designs')
        self.assertEqual((workspace.status(root)['gate'], self.kinds().count('section'),
                          self.built(root)['start']['design']['revision']),
                         ('deck', 4, status['revision']))

    def test_notes_alone_keep_the_design_approved_and_nothing_is_asked_of_the_tool(self):
        root = self.begin()
        self.drawn(root)
        self.workers.outline_said = with_slide(2, notes='8 min. Health checks pace it.')
        self.decide(root, 'deck', 'revise', 'Give the third slide more time.')
        shown = self.view(root)['outline']
        self.assertEqual((shown['waiting'], shown['design']['asked']), (True, []))
        self.engine.outline(root, None, 'approve', seen=shown['sha256'],
                            design=shown['design']['revision'])
        self.assertEqual(len(self.slides.replies), 1, 'the tool had nothing to ask')
        self.assertEqual(workspace.status(root)['gate'], 'deck')

    def test_a_design_sent_back_unchanged_cannot_be_approved_until_it_changes(self):
        root = self.begin()
        self.to_outline(root)
        self.engine.outline(root, None, 'revise', 'Draw the second slide as a loop.')
        self.assertEqual(self.slides.replies[-1]['feedback'], 'Draw the second slide as a loop.')
        shown = self.view(root)['outline']
        self.assertTrue(shown['waiting'])
        self.assertIn(pipeline.UNCHANGED, shown['worth'])
        self.assertEqual(len(shown['design']['asked']), 6, 'nothing is shown as approved')
        with self.assertRaisesRegex(WorkspaceError, 'has not approved it. Ask for changes.'):
            self.engine.outline(root, None, 'approve', design=shown['design']['revision'])
        changed = runner_support.designed(OUTLINE)
        changed['slides'][1]['intent']['relationship'] = 'cycle'
        self.workers.design_said = changed
        self.engine.outline(root, None, 'revise', 'Draw the second slide as a loop.')
        self.assertEqual(len(self.slides.replies), 1, 'the tool was not asking: nothing sent')
        shown = self.view(root)['outline']
        self.assertNotIn(pipeline.UNCHANGED, shown['worth'])
        self.engine.outline(root, None, 'approve', design=shown['design']['revision'])
        self.assertEqual(workspace.status(root)['gate'], 'deck')

    def test_visual_13_stale_decision_refused(self):
        root = self.begin()
        shown = self.to_outline(root)['outline']
        before = (self.record(root)['deck'][''], self.session(root))
        with self.assertRaisesRegex(WorkspaceError, 'has changed since it was opened'):
            self.engine.outline(root, None, 'approve', seen=shown['sha256'], design='0' * 64)
        # The tool's question moved under the page: someone proposed another design there.
        changed = self.proposal(root)
        changed['slides'][1]['composition'] = 'Three boxes in a column.'
        other = root.parent / 'other.json'
        other.write_text(json.dumps(changed))
        self.slides.design_propose(root / pipeline.DESIGNS, other, before[1]['revision'])
        moved = self.session(root)
        with self.assertRaisesRegex(WorkspaceError, 'has changed since it was opened'):
            self.engine.outline(root, None, 'approve', seen=shown['sha256'],
                                design=shown['design']['revision'])
        self.assertEqual(self.slides.replies[-1]['planRevision'], shown['design']['revision'])
        self.assertEqual((self.record(root)['deck'][''], self.session(root)),
                         (before[0], moved), 'the proposal and approvals are as they were')
        self.assertNotIn('approved', self.record(root)['deck'][''])
        self.assertEqual(self.kinds().count('section'), 0)

def with_assets(design: dict, generated: bool = False) -> dict:
    """The design of OUTLINE with a screenshot the person supplies on its first content slide,
    and with `generated`, the slide after it drawn as generated art."""
    design = json.loads(json.dumps(design))
    first, second = design['slides'][1], design['slides'][2]
    first['asset']['candidates'].append({
        'assetId': 'console_view', 'kind': 'screenshot', 'ref': 'The restart in the console',
        'concept': 'Instances replaced in turn', 'status': 'pending'})
    if generated:
        second['intent']['visual']['family'] = 'generated-art'
        second['asset']['candidates'] = [{
            'assetId': 'capacity_art', 'kind': 'generated', 'ref': 'Two instances sharing load',
            'concept': 'Capacity held by the others', 'status': 'pending'}]
    return design


DRAWING = {'slide': 'what-it-does', 'criterion': 'visual-relationship', 'severity': 'major',
           'about': 'drawing', 'reason': 'The steps sit in a column with nothing joining them.',
           'fix': 'Join each step to the next with an edge.'}
CONCEPT = {'slide': 'when-capacity-holds', 'criterion': 'explanatory-value',
           'severity': 'major', 'about': 'concept',
           'reason': 'A diagram of boxes cannot show why one instance loses capacity.'}


class JudgedTests(DeckCase):
    """A slides tool that reviews a whole deck against its approved design: the reviewer
    answers the tool's own assessment, a drawing finding is drawn again within its limits,
    and one that needs other words or another concept takes what the deck says back to the
    person. Rows V04, V08 and V09 of the state-transition matrix in
    docs/superpowers/plans/2026-10-14-visual-teaching-in-decks.md."""

    def setUp(self):
        super().setUp()
        self.slides.design, self.slides.judges = True, True
        self.slides.have['local'] = True    # the tool renders what it reviews with LibreOffice

    def called(self, name: str) -> list[tuple]:
        return [call for call in self.slides.calls if call[0] == name]

    def review_folder(self, root: Path, made: dict | None = None) -> Path:
        made = made or self.built(root)['rounds'][-1]
        return root / pipeline.WORK / made['preview']

    def test_a_deck_drawn_from_its_design_is_reviewed_against_it_and_that_deck_is_kept(self):
        root = self.begin()
        self.drawn(root)
        self.assertEqual(workspace.status(root)['gate'], 'deck')
        start = self.built(root)['start']
        self.assertEqual(start['review'], pipeline.JUDGED)
        [made] = self.built(root)['rounds']
        # The whole deck was rendered and reviewed by the slides tool, not previewed apart.
        self.assertEqual([call[-1] for call in self.called('preview_design')],
                         ['section=True', 'section=True'])
        self.assertEqual(len(self.called('review_prepare')), 1)
        self.assertEqual(len(self.called('review_slide')), len(OUTLINE['slides']) + 1,
                         'each slide for its packet, and the receipts before it is kept')
        self.assertEqual(self.called('critique'), [], 'no second scorer')
        review = self.review_folder(root, made)
        record = json.loads((review / 'review.json').read_text())
        self.assertEqual((record['visualReviewComplete'], record['creativeReviewComplete'],
                          record['readyForUserReview']), (True, True, True))
        # The reviewer answered the tool's own criteria, and passed every one.
        job, spec = [(job, spec) for kind, job, spec in self.workers.jobs if kind == 'review'][0]
        self.assertEqual(job.guidance, briefs.guidance('deck-review', design=True))
        self.assertIn('submit_judgements', job.task)
        self.assertTrue(spec['review']['judged']['packets'])
        assessed = self.slides.assessed[-1]
        self.assertEqual([slide['id'] for slide in assessed['slides']],
                         [slide['id'] for slide in OUTLINE['slides']])
        self.assertEqual({check['status'] for slide in assessed['slides']
                          for check in slide['checks']}, {'pass'})
        # The deck kept is the one the tool rendered, whose pictures the page shows.
        kept = root / workspace.artifact(root, workspace.load(root), 'deck')['file']
        self.assertEqual(kept.read_bytes(), (review / 'deck.pptx').read_bytes())
        self.assertEqual(made['deck'], workspace.sha256_file(review / 'deck.pptx'))
        shown = self.gate(root)
        self.assertEqual(shown['review']['findings'], [])
        self.assertEqual([entry['slide'] for entry in shown['review']['direct']],
                         ['cover-restarts', 'closing-practice'])
        self.assertEqual({entry['accepted'] for entry in shown['review']['direct']}, {True})
        self.assertEqual([slide['number'] for slide in shown['slides']],
                         list(range(1, len(OUTLINE['slides']) + 1)))
        self.assertEqual(self.engine.picture(root, 2, 'deck'), png(2))
        note = (root / 'reviews' / 'deck.md').read_text().replace('> ', '')
        self.assertIn('Drawn as text by decision, and accepted so by the review: slide 1, '
                      'slide 6.', note)

    def test_visual_04_fit_repair_preserves_design(self):
        self.workers.found = [[{**DRAWING, 'criterion': 'technical-fit',
                                'reason': 'The second label wraps onto three lines.'}]]
        root = self.begin()
        self.drawn(root)
        approved = self.record(root)['deck']['']['approved']
        self.assertEqual(self.kinds()[-6:], ['outline', 'section', 'section', 'review',
                                             'section', 'review'])
        self.assertEqual(self.record(root)['deck']['']['approved'], approved)
        self.assertEqual(len(self.slides.replies), 1, 'nothing asked of the person again')
        # The render and the assessment are made again for the deck drawn again.
        rounds = self.built(root)['rounds']
        self.assertEqual(len(self.called('review_prepare')), 2)
        self.assertNotEqual(rounds[0]['judged']['revision'], rounds[1]['judged']['revision'])
        self.assertEqual(rounds[0]['review']['findings'][0]['category'], 'fit-defect')
        self.assertEqual(workspace.status(root)['gate'], 'deck')

    def test_visual_08_drawing_finding_repairs_section(self):
        self.workers.found = [[DRAWING], [DRAWING], [DRAWING]]
        root = self.begin()
        view = self.drawn(root)
        approved = self.record(root)['deck']['']['approved']
        # Drawn again within its limits: twice, then the deck comes as it is.
        self.assertEqual((self.kinds().count('review'), self.kinds().count('section')), (3, 4))
        job, spec = [(job, spec) for kind, job, spec in self.workers.jobs
                     if kind == 'section'][-1]
        self.assertEqual(spec['artifacts']['section']['prefix'], 's1_')
        self.assertEqual(job.guidance, briefs.guidance('deck-section', repair=True,
                                                       design=True, beyond=True))
        self.assertTrue(spec['artifacts']['section']['beyond'])
        told = deck.told(self.built(root)['rounds'][0]['review']['findings'],
                         [{'number': 2, 'id': 'what-it-does', 'title': 'Steps'}])
        self.assertIn('- **major**, Whether the visual teaches, `visual-relationship`: The steps '
                      'sit in a column with nothing joining them. Suggested: Join each step', told)
        self.assertEqual((view['state'], workspace.status(root)['gate']), ('waiting', 'deck'))
        self.assertEqual(self.record(root)['deck']['']['approved'], approved)
        self.assertEqual(self.record(root)['deck'][''].get('returns'), None)
        shown = self.gate(root)
        self.assertEqual(shown['review']['round'], 3)
        self.assertEqual(shown['review']['findings'], [{
            'slide': 'what-it-does', 'number': 2, 'severity': 'major', 'about': 'drawing',
            'note': DRAWING['reason'], 'fix': DRAWING['fix'], 'category': 'visual-teaching',
            'criterion': 'visual-relationship'}])
        note = (root / 'reviews' / 'deck.md').read_text().replace('> ', '')
        self.assertIn('- Slide 2, major, whether the visual teaches, about how it is drawn: The '
                      'steps sit in a column', note)

    def test_visual_09_content_change_returns_to_outline(self):
        self.workers.found = [[DRAWING, CONCEPT]]
        root = self.begin()
        first = self.drawn(root)
        # Nothing is drawn again: what the deck says comes back to the person, with why.
        self.assertEqual((first['outline']['waiting'], workspace.status(root)['gate']),
                         (True, None))
        self.assertEqual((self.kinds().count('review'), self.kinds().count('section')), (1, 2))
        kept = self.record(root)['deck']['']
        self.assertIsNone(kept['approved'])
        [back] = kept['returns']
        self.assertEqual((back['approved']['by'], back['start'], [finding['slide'] for finding
                                                                  in back['findings']]),
                         ('page', self.built(root)['start']['folder'],
                          ['when-capacity-holds']))
        self.assertEqual(back['findings'][0]['about'], 'concept')
        worth = first['outline']['worth']
        self.assertEqual(worth[0], pipeline.RETURNED)
        self.assertIn('Slide 3, major, about the visual concept it was approved with: A '
                      'diagram of boxes cannot show why', worth[1])
        self.assertEqual(len(self.slides.replies), 1, 'nothing is sent to the slides tool')
        self.assertIn('keep the review of the slide deck, and take what the slide deck says '
                      'back to you', self.log()[-2])
        # Asked for changes: the writer is told why, and the new words and design are put to
        # the person before anything is drawn again.
        self.workers.outline_said = with_slide(2, title='Capacity holds with two instances')
        shown = self.engine.outline(root, None, 'revise', 'Show the load moving across.',
                                    seen=first['outline']['sha256'],
                                    design=first['outline']['design']['revision'])
        task = self.workers.of('outline')[-1].task
        for said in ('Show the load moving across.', 'or how they were approved to teach',
                     '- when-capacity-holds: A diagram of boxes cannot show why'):
            self.assertIn(said, task)
        self.assertEqual(shown['outline']['waiting'], True)
        self.engine.outline(root, None, 'approve', seen=shown['outline']['sha256'],
                            design=shown['outline']['design']['revision'])
        self.assertEqual(workspace.status(root)['gate'], 'deck')
        self.assertEqual(len(self.called('outline_start')), 2, 'drawn from the new approval')
        self.assertEqual(self.record(root)['deck']['']['returns'][0]['findings'],
                         back['findings'], 'the history is kept')

    def test_approved_as_it_stands_the_deck_is_drawn_on_with_what_was_found(self):
        self.workers.found = [[DRAWING, CONCEPT]]
        root = self.begin()
        first = self.drawn(root)
        self.engine.outline(root, None, 'approve', seen=first['outline']['sha256'],
                            design=first['outline']['design']['revision'])
        # The same start: its drawing finding is drawn again, and it is not sent back twice.
        self.assertEqual(len(self.called('outline_start')), 1)
        self.assertEqual((self.kinds().count('section'), self.kinds().count('review')), (3, 2))
        self.assertEqual(len(self.record(root)['deck']['']['returns']), 1)
        self.assertEqual(workspace.status(root)['gate'], 'deck')
        self.assertEqual(len(self.slides.replies), 1)

    def test_a_composer_drawing_again_says_what_only_the_outline_can_put_right(self):
        self.workers.found = [[DRAWING]]

        def beyond(tools, job):
            made = json.dumps(drawn(tools.job['artifacts']['section']))
            assert tools.preview_section(made)[0]
            accepted = tools.submit_section(made, 'Nothing.', 'The first slide.', [
                {'slide': 'what-it-does', 'why': 'Only a sequence of three boxes is approved, '
                 'and the steps need a loop.'}])
            assert accepted[0], accepted[1]
        root = self.begin()
        self.to_outline(root)
        self.workers.queued['section'] = [self.workers.section, self.workers.section, beyond]
        view = self.engine.outline(root, None, 'approve')
        self.assertTrue(view['outline']['waiting'])
        [back] = self.record(root)['deck']['']['returns']
        self.assertEqual(back['findings'], [{
            'slide': 'what-it-does', 'number': 2, 'severity': 'major', 'about': 'concept',
            'note': 'Only a sequence of three boxes is approved, and the steps need a loop.',
            'by': 'composer'}])
        self.assertIn('said by whoever drew it again', view['outline']['worth'][1])

    def test_a_review_that_no_longer_holds_is_built_and_reviewed_again(self):
        def tampered(tools, job):
            self.workers.review(tools, job)
            picture = next(Path(tools.job['review']['judged']['output']).glob('slide-002-*'))
            picture.write_bytes(png(99))
        self.workers.then('review', tampered)
        root = self.begin()
        self.drawn(root)
        rounds = self.built(root)['rounds']
        self.assertEqual((len(rounds), self.kinds().count('review'),
                          len(self.called('review_prepare'))), (1, 2, 2))
        self.assertNotIn('stale', self.built(root)['rounds'][0], 'built again in its place')
        self.assertEqual(workspace.status(root)['gate'], 'deck')
        review = self.review_folder(root)
        kept = root / workspace.artifact(root, workspace.load(root), 'deck')['file']
        self.assertEqual(kept.read_bytes(), (review / 'deck.pptx').read_bytes())

    def test_a_changed_reviewed_deck_is_rendered_and_reviewed_again(self):
        def tampered(tools, job):
            self.workers.review(tools, job)
            deck_file = Path(tools.job['review']['judged']['output']) / 'deck.pptx'
            deck_file.write_bytes(deck_file.read_bytes() + b' ')
        self.workers.then('review', tampered)
        root = self.begin()
        self.drawn(root)
        self.assertEqual((len(self.built(root)['rounds']), self.kinds().count('review')),
                         (1, 2))
        self.assertEqual(workspace.status(root)['gate'], 'deck')

    def test_without_libreoffice_the_review_stops_and_says_what_to_install(self):
        self.slides.have['local'] = False
        root = self.begin()
        view = self.drawn(root)
        self.assertEqual(view['state'], 'stopped')
        self.assertIn('The slides tool reviews a deck against its approved design by rendering '
                      'it on this computer, and it cannot: soffice is not installed.',
                      view['problem']['what'])
        self.assertEqual(self.kinds().count('review'), 0)

    def test_a_deck_started_for_this_review_stops_where_the_tool_can_no_longer_review(self):
        self.workers.then('section', *[fails()] * 6)
        root = self.begin()
        self.drawn(root)
        self.slides.judges = False
        # The sections are drawn side by side, so the other one may not have used all its
        # failures before the training stopped. Whatever is left must not fail the retry.
        self.workers.queued.pop('section', None)
        view = self.engine.act(root, 'retry')
        self.assertEqual(view['problem']['what'], self.engines.REVIEW_GONE)
        self.assertEqual(self.called('review_prepare'), [])

    def test_a_tool_that_cannot_review_against_the_design_reviews_as_before(self):
        self.slides.judges = False
        root = self.begin()
        self.drawn(root)
        self.assertNotIn('review', self.built(root)['start'])
        self.assertEqual(self.called('review_prepare'), [])
        self.assertEqual(len(self.called('critique')), 1)
        job = [job for kind, job, _ in self.workers.jobs if kind == 'review'][0]
        self.assertEqual(job.guidance, briefs.guidance('deck-review'))
        self.assertNotIn('direct', self.gate(root)['review'])


class AssetTests(DeckCase):
    """A slides tool that keeps the deck's assets: the icons an approved design names are found
    and recorded before any section is drawn, a picture is the person's to supply on the page,
    and what is drawn is made from what each asset is now. Rows V05, V06 and V07 of the
    state-transition matrix in docs/superpowers/plans/2026-10-14-visual-teaching-in-decks.md."""

    def setUp(self):
        super().setUp()
        self.slides.design = self.slides.keeps = True
        self.workers.design_said = with_assets(runner_support.designed(OUTLINE))

    def supply(self, root: Path, shade: int = 40, asset: str = 'console_view') -> dict:
        return self.engine.supply_asset(root, None, asset, png(shade), 'The console mid-restart',
                                        'Course author, October 2026', 'Internal training only')

    def listed(self, view: dict) -> dict:
        return {entry['asset']: entry['state'] for entry in view['deck']['assets']}

    def test_icons_are_found_and_recorded_before_any_section_is_drawn(self):
        root = self.begin()
        self.drawn(root)
        self.supply(root)
        recorded = pipeline.recorded(root, None)
        self.assertEqual((recorded['icon_instance']['kind'], recorded['icon_instance']['ref']),
                         ('icon', 'icon-server'))
        names = [call[0] for call in self.slides.calls]
        self.assertLess(names.index('asset_icon'), names.index('outline_start'))
        start = next((root / 'work' / 'deck').glob('start-*'))
        brief = (start / 'given' / 'section-1.md').read_text()
        for told in ('- An instance: `icon-server`, recorded as `icon_instance`, on '
                     '`what-it-does`', deck.PLACED[0],
                     'screenshot "The restart in the console" for Instances replaced in turn, '
                     'recorded as `console_view`: place it by that asset ID'):
            self.assertIn(told, brief)
        job, spec = [(job, spec) for kind, job, spec in self.workers.jobs
                     if kind == 'section'][0]
        self.assertEqual(job.guidance, briefs.guidance('deck-section', design=True,
                                                       assets=True))
        self.assertEqual(spec['artifacts']['section']['assets'],
                         {'project': str(root / pipeline.DESIGNS), 'generated': {}})
        # The manifest and the picture are shared with the design they belong to.
        tracked = self.git('ls-files', 'trainings/rolling-restarts').splitlines()
        for kept in ('deck/.harness-slides/assets.json', 'deck/assets/supplied/console_view.png'):
            self.assertIn(f'trainings/rolling-restarts/{kept}', tracked)
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_visual_05_missing_asset_waits(self):
        self.workers.design_said = with_assets(runner_support.designed(OUTLINE), generated=True)
        self.workers.placing = {'what-it-does': [
            {'type': 'image', 'id': 's1_console', 'asset': 'console_view'}]}
        root = self.begin()
        view = self.drawn(root)
        approved = self.record(root)['deck']['']['approved']
        self.assertEqual((view['state'], view['problem']['action']), ('waiting', 'retry'))
        said = view['problem']['what']
        for told in ('The deck is not drawn until what its approved design uses is to hand.',
                     'Slide `what-it-does` needs the screenshot "The restart in the console" '
                     '(Instances replaced in turn). Supply it on this page.',
                     'Slide `when-capacity-holds` is drawn as generated art, "Two instances '
                     "sharing load\" (Capacity held by the others), and the slides tool's image "
                     'provider (gemini-api) is not set up: key_required.', 'GEMINI_API_KEY'):
            self.assertIn(told, said)
        self.assertEqual(view['problem']['kept'], self.engines.ASSETS_KEPT)
        self.assertEqual(self.listed(view), {'icon_instance': 'recorded',
                                             'console_view': 'wanted',
                                             'capacity_art': 'wanted'})
        self.assertEqual([entry['supply'] for entry in view['deck']['assets']],
                         [False, True, False])
        # The approval and what was saved stay; nothing is started or asked again.
        self.assertEqual(self.record(root)['deck']['']['approved'], approved)
        self.assertEqual(([call[0] for call in self.slides.calls].count('outline_start'),
                          self.kinds().count('section'), len(self.slides.replies)), (0, 0, 1))
        self.assertEqual(self.engine.act(root, 'retry')['problem']['what'], said,
                         'trying again waits again, for the same things')
        # A file gone from under a deck already drawn waits too, before anything is drawn.
        self.slides.env = {'GEMINI_API_KEY': 'set'}
        self.supply(root)
        self.assertEqual(workspace.status(root)['gate'], 'deck')
        sections = self.kinds().count('section')
        (root / 'deck' / 'assets' / 'supplied' / 'console_view.png').unlink()
        self.engine.wake(root)
        view = self.view(root)
        self.assertEqual(view['state'], 'waiting')
        self.assertIn('console_view: file assets/supplied/console_view.png is missing from the '
                      'project. Supply it again on this page, or put the file back.',
                      view['problem']['what'])
        self.assertEqual(self.kinds().count('section'), sections, 'nothing drawn without it')
        self.assertEqual(self.listed(view)['console_view'], 'missing')

    def test_visual_06_asset_resolution_resumes(self):
        root = self.begin()
        waiting = self.drawn(root)
        self.assertEqual(waiting['state'], 'waiting')
        approved = self.record(root)['deck']['']['approved']
        view = self.supply(root)
        self.assertIsNone(view['problem'])
        self.assertEqual((workspace.status(root)['gate'], len(self.slides.replies)), ('deck', 1),
                         'drawn to its gate with the one decision already made')
        self.assertEqual(self.record(root)['deck']['']['approved'], approved)
        recorded = pipeline.recorded(root, None)['console_view']
        self.assertEqual((recorded['kind'], recorded['alt'], recorded['source'],
                          recorded['restrictions']),
                         ('screenshot', 'The console mid-restart', 'Course author, October 2026',
                          'Internal training only'))
        start = self.built(root)['start']
        self.assertEqual(set(start['assets']), {'icon_instance', 'console_view'})
        self.assertEqual(self.kinds().count('section'), 2)
        # A picture is the person's alone, and only one the approved design asks for.
        for asset, data, why in (('icon_instance', png(), 'is not a picture the approved'),
                                 ('console_view', b'not a picture', 'PNG, JPEG or GIF')):
            with self.assertRaisesRegex(WorkspaceError, why):
                self.engine.supply_asset(root, None, asset, data, 'Alt', 'Source')

    def test_visual_07_asset_change_invalidates_build(self):
        shot = {'type': 'image', 'id': 's1_console', 'asset': 'console_view'}
        self.workers.placing = {'what-it-does': [shot]}
        root = self.begin()
        self.drawn(root)
        self.supply(root, shade=40)
        built = self.built(root)
        first = built['sections']['section-1']
        self.assertEqual(set(first['assets']), {'console_view'})
        self.assertEqual(built['sections']['section-2']['assets'], {})
        self.assertEqual(built['rounds'][-1]['assets'], first['assets'])
        jobs, rounds = len(self.workers.jobs), len(built['rounds'])
        saved = self.record(root)['deck']['']['saved']
        # The person gives another picture for it, at the deck's gate.
        view = self.supply(root, shade=200)
        drawn_again = [spec['artifacts']['section']['slides'][0]['id']
                       for kind, _, spec in self.workers.jobs[jobs:] if kind == 'section']
        self.assertEqual(drawn_again, ['what-it-does'], 'only the section that shows it')
        self.assertEqual(self.kinds(jobs)[-1], 'review')
        built = self.built(root)
        self.assertEqual(len(built['rounds']), rounds + 1)
        self.assertNotEqual(built['rounds'][-1]['assets'], first['assets'])
        self.assertEqual(built['sections']['section-1']['assets'], built['rounds'][-1]['assets'])
        self.assertNotEqual(self.record(root)['deck']['']['saved'], saved)
        self.assertEqual((view['problem'], workspace.status(root)['gate'],
                          len(self.slides.replies)), (None, 'deck', 1))
        # A file changed underneath, with no new picture given, is stale as well.
        (root / 'deck' / 'assets' / 'supplied' / 'console_view.png').write_bytes(png(7))
        found = self.engine._survey(root, self.record(root)).decks[None]
        self.assertNotIn('deck-sections', found.done)
        self.assertEqual(found.todo, ('section-1',))

    def test_a_tool_without_the_manifest_draws_as_before(self):
        self.slides.keeps = False
        root = self.begin()
        self.drawn(root)
        self.assertEqual(workspace.status(root)['gate'], 'deck')
        self.assertNotIn('assets', self.built(root)['start'])
        self.assertFalse((root / pipeline.ASSETS).exists())
        job, spec = [(job, spec) for kind, job, spec in self.workers.jobs
                     if kind == 'section'][0]
        self.assertEqual(job.guidance, briefs.guidance('deck-section', design=True))
        self.assertNotIn('assets', spec['artifacts']['section'])
        self.assertNotIn('assets', self.view(root)['deck'] or {})


class AdoptionTests(DeckCase):
    """What Harness Slides 0.14.1 lists beyond 0.14.0, used where the slides tool lists it,
    and the way before it where it does not. Each is tried both ways: `listed` is what the
    tool says it has, and a name taken out of it plays a build without that one."""

    def setUp(self):
        super().setUp()
        self.slides.design = self.slides.keeps = self.slides.judges = True
        self.slides.have['local'] = True
        self.slides.listed = set(slides_stand_in.CURRENT)

    def without(self, *names: str) -> None:
        self.slides.listed -= set(names)

    def called(self, name: str) -> list[tuple]:
        return [call for call in self.slides.calls if call[0] == name]

    def test_what_an_approved_design_still_wants_is_said_by_the_tool_that_reads_it(self):
        said = {}
        for title, older in (('Rolling restarts', False), ('Rolling restarts again', True)):
            if older:
                self.without('assets-approved-candidates')
            self.workers.design_said = with_assets(runner_support.designed(OUTLINE))
            root = self.begin(title=title)
            view = self.drawn(root)
            self.assertEqual(view['state'], 'waiting')
            project = str(root / pipeline.DESIGNS)
            checks = [call for call in self.called('asset_check') if call[1] == project]
            self.assertEqual(checks[-1][2:], () if older else (f'design={project}',))
            said[older] = view['problem']['what']
        self.assertEqual(said[True], said[False], 'the same words either way')
        self.assertIn('Slide `what-it-does` needs the screenshot "The restart in the console" '
                      '(Instances replaced in turn). Supply it on this page.', said[True])

    def test_an_icon_is_named_by_its_library_id_where_the_tool_takes_one(self):
        design = runner_support.designed(OUTLINE)
        design['slides'][1]['asset']['candidates'][0].update(ref='icon-server',
                                                             refType='library-id')
        self.workers.design_said = design
        searched = []
        found = self.brand.icons
        self.brand.icons = lambda words, limit=5: searched.append(words) or found(words, limit)
        root = self.begin()
        self.drawn(root)
        job, spec = [(job, spec) for kind, job, spec in self.workers.jobs
                     if kind == 'outline'][-1]
        self.assertEqual(job.guidance, briefs.guidance('deck-outline', design=True, icons=True))
        self.assertTrue(spec['artifacts']['outline']['icons'])
        self.assertIn('## Icons by their exact ID', job.guidance)
        proposed = self.called('design_propose')
        self.assertTrue(proposed and all(call[-1].startswith('brand=') for call in proposed))
        self.assertEqual(pipeline.recorded(root, None)['icon_instance']['ref'], 'icon-server')
        self.assertEqual(searched, [], 'an icon named by its ID is not searched for')
        # The tool before it takes no library ID, so neither the writer nor the tool is told.
        self.without('design-icon-ids')
        self.workers.design_said = runner_support.designed(OUTLINE)
        root = self.begin(title='Rolling restarts again')
        self.drawn(root)
        job, spec = [(job, spec) for kind, job, spec in self.workers.jobs
                     if kind == 'outline'][-1]
        self.assertEqual(job.guidance, briefs.guidance('deck-outline', design=True))
        self.assertNotIn('icons', spec['artifacts']['outline'])
        self.assertFalse(self.called('design_propose')[-1][-1].startswith('brand='))
        self.assertEqual(searched, ['server'], 'a free name is found in the library')

    def test_a_recorded_icon_is_placed_by_its_asset_id_where_the_tool_can(self):
        self.workers.placing = {'what-it-does': [
            {'type': 'icon', 'id': 's1_instance', 'asset': 'icon_instance'}]}
        root = self.begin()
        self.drawn(root)
        start = self.built(root)['start']
        self.assertEqual(start['icons'], 'asset')
        brief = (root / 'work' / 'deck' / start['folder'] / 'given' / 'section-1.md').read_text()
        for told in ('Place each by the asset ID it is recorded as',
                     '"type": "icon", "id": "<your ID>", "asset": "<asset ID>"',
                     '- An instance: recorded as `icon_instance`, the icon `icon-server`, on'):
            self.assertIn(told, brief)
        spec = [spec for kind, _, spec in self.workers.jobs if kind == 'section'][0]
        self.assertEqual(spec['artifacts']['section']['assets']['icons'], 'asset')
        drawn = self.built(root)['sections']['section-1']
        self.assertIn('icon_instance', drawn['assets'], 'what it draws is fingerprinted')
        compiled = root / 'work' / 'deck' / self.built(root)['rounds'][-1]['compiled']
        report = json.loads((compiled / 'compose-report.json').read_text())
        self.assertEqual([(entry['asset'], entry['kind']) for entry
                          in report['inputs']['assets']], [('icon_instance', 'icon')])
        # The tool before it places an icon only by its library ID.
        self.without('compose-icon-assets')
        self.workers.placing = None
        root = self.begin(title='Rolling restarts again')
        self.drawn(root)
        start = self.built(root)['start']
        self.assertNotIn('icons', start)
        brief = (root / 'work' / 'deck' / start['folder'] / 'given' / 'section-1.md').read_text()
        self.assertIn('Use each ID as the `icon` of an icon node', brief)
        self.assertNotIn('"asset": "<asset ID>"}`. `search', brief)

    def test_every_slides_packet_comes_in_one_call_where_the_tool_gives_them(self):
        prompts = {}
        for title, older in (('Rolling restarts', False), ('Rolling restarts again', True)):
            if older:
                self.without('review-packets')
            self.slides.calls.clear()
            root = self.begin(title=title)
            self.drawn(root)
            self.assertEqual(workspace.status(root)['gate'], 'deck')
            made = self.built(root)['rounds'][-1]
            folder = root / 'work' / 'deck' / made['folder']
            prompts[older] = [packet['slide'] for packet
                              in json.loads((folder / 'packets.json').read_text())]
            self.assertEqual((len(self.called('review_packets')),
                              len(self.called('review_slide'))),
                             (0, len(OUTLINE['slides']) + 1) if older else (1, 1),
                             'the one left is the check of the receipts before it is kept')
            self.assertEqual(made['deck'], workspace.sha256_file(folder / 'review' /
                                                                 'deck.pptx'))
            self.assertEqual(made['file'], (folder / 'review' / 'deck.pptx').relative_to(
                root / 'work' / 'deck').as_posix())
        self.assertEqual(prompts[True], prompts[False], 'the reviewer is told the same')

    def test_a_review_is_rendered_through_drive_where_previews_go_and_the_tool_can(self):
        self.slides.have['local'] = False   # no LibreOffice: previews go through Drive
        self.without('review-google-renderer')
        root = self.begin()
        view = self.drawn(root)
        self.assertEqual(view['state'], 'stopped')
        self.assertIn('rendering it on this computer, and it cannot', view['problem']['what'])
        self.slides.listed.add('review-google-renderer')
        view = self.engine.act(root, 'retry')
        self.assertEqual((view['state'], workspace.status(root)['gate']), ('waiting', 'deck'),
                         view.get('problem'))
        [prepared] = [call for call in self.called('review_prepare')
                      if 'renderer=google' in call]
        self.assertEqual(prepared[-1], f'file={self.slides.files[-1]}',
                         "the deck's one file in Drive is written again")
        self.assertEqual(self.slides.reviewed, [self.slides.files[-1]])

    def test_an_assessment_leaves_its_sources_to_the_slide_where_the_tool_takes_them(self):
        root = self.begin()
        self.drawn(root)
        self.assertEqual({'sources' in check for slide in self.slides.assessed[-1]['slides']
                          for check in slide['checks']}, {False})
        record = json.loads((root / 'work' / 'deck' / self.built(root)['rounds'][-1]['preview']
                             / 'review.json').read_text())
        self.assertEqual(record['creativeAssessment']['slides'][1]['checks'][0]['sources'],
                         ['O1'], 'the tool took the slide its own')
        self.without('review-sources-from-slide')
        root = self.begin(title='Rolling restarts again')
        self.drawn(root)
        self.assertEqual({'sources' in check for slide in self.slides.assessed[-1]['slides']
                          for check in slide['checks']}, {True})

    def test_a_deck_is_put_to_the_person_with_its_findings_and_their_approval_sent(self):
        reason = 'The second label wraps onto three lines.'
        self.workers.found = [[{**DRAWING, 'criterion': 'technical-fit', 'severity': 'minor',
                                'reason': reason}]]
        root = self.begin()
        self.drawn(root)
        presented = self.record(root)['deck']['']['presented']
        question = presented['question']
        self.assertEqual((question['findings'], question['options'][0], presented['deck']),
                         (1, 'Approve these slides with the findings listed',
                          workspace.sha256_file(root / 'deck.pptx')))
        project = pipeline.place(root, None, pipeline.DESIGNS)
        status = self.slides.design_status(project)
        self.assertEqual(([found['detail'] for found in status['renderedFindings']],
                          status['renderedAcceptance']), ([reason], False))
        # A refusal by the tool keeps the core from recording the approval.
        self.slides.refuse['design_respond'] = ['Rendered review changed; present current '
                                                'output']
        with self.assertRaisesRegex(desk.Refusal, 'did not take your approval of the deck'):
            self.decide(root, 'deck')
        self.assertEqual(workspace.status(root)['artifacts']['deck'], 'draft')
        del self.slides.refuse['design_respond']
        self.decide(root, 'deck')
        self.assertEqual(workspace.status(root)['artifacts']['deck'], 'approved')
        sent = self.slides.replies[-1]
        self.assertEqual((sent['questionId'], sent['decision'], sent['feedback']),
                         (question['id'], 'approve',
                          'Approve these slides with the findings listed'))
        self.assertTrue(self.slides.design_status(project)['renderedAcceptance'])
        self.assertTrue(self.record(root)['deck']['']['presented']['answered'])
        # The tool before it presents nothing, and only the outline's answer is ever sent.
        self.without('design-present-findings')
        self.slides.replies.clear()
        root = self.begin(title='Rolling restarts again')
        self.drawn(root)
        self.assertIsNone(self.record(root)['deck']['']['presented'])
        self.decide(root, 'deck')
        self.assertEqual(len(self.slides.replies), 1)

    def test_an_intent_is_handed_in_as_written_where_the_tool_ignores_key_order(self):
        def section(tools, job):
            made = drawn(tools.job['artifacts']['section'])
            for slide in made['slides']:    # copied with its keys in another order
                slide['intent'] = json.loads(json.dumps(slide['intent'], sort_keys=True))
            made = json.dumps(made)
            assert tools.preview_section(made)[0]
            assert tools.submit_section(made, 'Nothing.', 'The second slide.')[0]

        orders = {}
        for title, older in (('Rolling restarts', False), ('Rolling restarts again', True)):
            if older:
                self.without('canonical-digests')
            self.workers.section = section
            root = self.begin(title=title)
            self.drawn(root)
            self.assertEqual(workspace.status(root)['gate'], 'deck')
            kept = json.loads((root / 'work' / 'deck' / self.built(root)['sections'][
                'section-1']['file']).read_text())
            orders[older] = list(kept['slides'][0]['intent'])
        approved = approved_plan()['slides'][1]['intent']
        self.assertEqual((orders[False], orders[True]), (sorted(approved), list(approved)))


class CompatibleTests(DeckCase):
    """A slides tool as released, 0.13.1, with no design session, and trainings that were
    already under way when a newer tool came. Rows V10, V11 and V12 of the state-transition
    matrix in docs/superpowers/plans/2026-10-14-visual-teaching-in-decks.md: a deck begun
    without a design carries on as it began, is drawn again from one only when the person
    asks, and a new deck waits for a tool that has what it needs."""

    def test_a_tool_without_a_design_session_puts_the_words_alone_to_the_person(self):
        root = self.begin()
        view = self.to_outline(root)
        spec = [spec for kind, _, spec in self.workers.jobs if kind == 'outline'][-1]
        self.assertFalse(spec['artifacts']['outline']['design'])
        self.assertEqual((view['outline']['design'], (root / pipeline.DESIGN).exists()),
                         (None, False))
        self.engine.outline(root, None, 'approve')
        self.assertEqual([call[0] for call in self.slides.calls
                          if call[0].startswith('design')], [])
        self.assertNotIn('design', self.record(root)['deck']['']['approved'])
        self.assertEqual(workspace.status(root)['gate'], 'deck')

    def test_a_deck_written_without_a_design_keeps_its_approval_when_the_tool_gains_one(self):
        root = self.begin()
        self.drawn(root)
        approved = self.record(root)['deck']['']['approved']
        self.slides.design = True
        self.engine.wake(root)
        self.engine.resume()
        self.assertEqual((workspace.status(root)['gate'], self.kinds().count('section')),
                         ('deck', 2), 'nothing is drawn again')
        self.assertEqual(self.record(root)['deck']['']['approved'], approved)
        # Asked for changes, it is written again as it was first written: words alone.
        self.workers.outline_said = with_slide(4, title='Check what you can explain')
        self.decide(root, 'deck', 'revise', 'Shorten the check slide.')
        view = self.view(root)
        self.assertEqual((view['outline']['waiting'], view['outline']['design']), (True, None))
        self.assertFalse((root / pipeline.DESIGN).exists())
        self.engine.outline(root, None, 'approve')
        self.assertEqual(self.slides.replies, [])
        self.assertEqual(workspace.status(root)['gate'], 'deck')

    def test_a_deck_waiting_at_its_gate_is_decided_as_it_was_put_when_the_tool_gains_one(self):
        root = self.begin()
        shown = self.to_outline(root)['outline']
        self.slides.design = True
        self.engine.outline(root, None, 'approve', seen=shown['sha256'])
        self.assertEqual((self.slides.replies, workspace.status(root)['gate']), ([], 'deck'))
        # Its sections are drawn as they always were, though the tool could check them now.
        self.assert_drawn_as_before(root)

    def assert_drawn_as_before(self, root: Path) -> None:
        """A deck without a design: its sections are told, held and built as before."""
        sections = [(job, spec) for kind, job, spec in self.workers.jobs if kind == 'section']
        self.assertTrue(sections)
        for job, spec in sections:
            made = spec['artifacts']['section']
            self.assertEqual(job.guidance, briefs.guidance('deck-section'))
            self.assertFalse({'design', 'section'} & set(made))
            for slide in made['slides']:
                self.assertEqual(sorted(slide), ['caveat', 'id', 'notes', 'points', 'source',
                                                 'sources', 'title'])
        start = next((root / 'work' / 'deck').glob('start-*'))
        self.assertFalse((start / pipeline.APPROVED_DESIGN).exists())
        self.assertEqual(json.loads((start / 'given' / 'outline.json').read_text())['house'],
                         list(deck.HOUSE))
        brief = (start / 'given' / 'section-1.md').read_text()
        self.assertIn(f'- {deck.HOUSE[-1]}', brief)
        self.assertNotIn('## The approved design', brief)
        self.assertEqual([call for call in self.slides.calls if call[0] == 'preview_design'
                          or (call[0] == 'compile' and len(call) != 4)], [])

    def test_a_deck_without_a_design_is_drawn_as_it_always_was(self):
        root = self.begin()
        self.drawn(root)
        self.assertEqual(workspace.status(root)['gate'], 'deck')
        self.assert_drawn_as_before(root)

    def test_a_deck_written_with_a_design_stops_where_the_tool_cannot_keep_one(self):
        self.slides.design = True
        root = self.begin()
        self.drawn(root)
        self.slides.design = False
        self.decide(root, 'deck', 'revise', 'Shorten the check slide.')
        view = self.view(root)
        self.assertEqual(view['state'], 'stopped')
        self.assertIn('which the slides tool on this computer cannot keep. Update '
                      'harness-slides', view['problem']['what'])
        self.assertTrue((root / pipeline.DESIGN).exists(), 'what was approved is kept')

    # --- rows V10, V11 and V12: a newer slides tool, and decks begun before it ---

    def test_visual_10_upgrade_preserves_existing_work(self):
        self.workers.then('section', *[fails()] * 6)
        root = self.begin()
        self.assertEqual(self.drawn(root)['state'], 'failed', 'approved, and still drawing')
        workspace.pin(root, 'harness-slides', 'deck', '0.13.1')
        pins, kept = workspace.load(root)['pins'], self.record(root)['deck']['']
        start = self.built(root)['start']
        # Harness Slides 0.14.1 is installed, with everything it lists, and looked at.
        self.slides.design = self.slides.keeps = self.slides.judges = True
        self.slides.have['local'] = True
        self.slides.listed = set(slides_stand_in.CURRENT)
        self.slides.calls.clear()
        # The sections are drawn side by side, so the other one may not have used all its
        # failures before the training stopped. Whatever is left must not fail the retry.
        self.workers.queued.pop('section', None)
        self.engine.look_again()
        self.assertEqual(self.record(root)['deck'][''], kept, 'nothing changes by itself')
        view = self.engine.act(root, 'retry')
        self.assertEqual((view['state'], workspace.status(root)['gate']), ('waiting', 'deck'),
                         view.get('problem'))
        self.assertEqual({key: self.record(root)['deck'][''].get(key)
                          for key in ('outline', 'approved')},
                         {key: kept.get(key) for key in ('outline', 'approved')})
        now = self.built(root)['start']
        self.assertEqual((now['folder'], now['design'], 'review' in now, 'assets' in now),
                         (start['folder'], None, False, False), 'drawn as it was begun')
        self.assertEqual([call[0] for call in self.slides.calls if call[0].startswith(
            ('design', 'review', 'asset', 'preview_design'))], [])
        self.assertEqual(view['redesign'], [{'level': None, 'artifact': 'deck',
                                             'label': workspace.label('deck'), 'may': True,
                                             'why': None}], 'offered, and never done for them')
        self.assertEqual(self.to_end(root), ['deck', 'scenario:main'])
        self.assertEqual(workspace.status(root)['artifacts']['deck'], 'approved')
        self.assertEqual(workspace.load(root)['pins'], pins, 'its pins are its own')
        self.assertEqual(self.record(root)['deck']['']['approved'], kept['approved'])

    def test_visual_11_explicit_redesign_migrates(self):
        root = self.begin()
        self.drawn(root)    # drawn without a design, and saved: the deck waits at its gate
        old, saved = self.record(root)['deck'][''], (root / 'deck.pptx').read_bytes()
        said = (root / pipeline.OUTLINE).read_text()
        others = {name: state for name, state in workspace.status(root)['artifacts'].items()
                  if name != 'deck'}
        # A tool that lacks what a new deck needs cannot draw it from a design.
        self.slides.lacking = ['compose-review']
        self.engine.deck_needs(fresh=True)
        [offered] = self.view(root)['redesign']
        self.assertFalse(offered['may'])
        self.assertIn(slides_tool.NAMES['compose-review'], offered['why'])
        with self.assertRaisesRegex(WorkspaceError, 'only where this computer can make one'):
            self.engine.redesign(root, None)
        # One that can is installed: nothing happens until the person asks.
        self.slides.lacking, self.slides.design = [], True
        self.engine.look_again()
        self.assertEqual(self.record(root)['deck'][''], old)
        view = self.engine.redesign(root, None)
        self.assertTrue(any('draw the slide deck again from a design, as asked on the page'
                            in line for line in self.log()))
        shown = view['outline']
        self.assertEqual((shown['waiting'], bool(shown['design'])), (True, True))
        kept = self.record(root)['deck']['']
        [history] = kept['history']
        self.assertEqual({key: history[key] for key in ('outline', 'approved', 'saved')},
                         {key: old[key] for key in ('outline', 'approved', 'saved')})
        self.assertEqual((root / history['folder'] / 'outline.json').read_text(), said)
        self.assertEqual((root / 'deck.pptx').read_bytes(), saved, 'readable until replaced')
        job = [job for kind, job, _ in self.workers.jobs if kind == 'outline'][-1]
        self.assertEqual(job.guidance, briefs.guidance('deck-outline', design=True))
        self.assertIn(pipeline.REDESIGNED, job.task)
        self.assertIn('The earlier draft:\n\n' + said.rstrip('\n'), job.task)
        self.assertEqual({name: state for name, state
                          in workspace.status(root)['artifacts'].items() if name != 'deck'},
                         others, 'nothing else changes')
        # Approved, it is drawn from its design, and the deck it replaces is kept as history.
        view = self.engine.outline(root, None, 'approve', seen=shown['sha256'],
                                   design=shown['design']['revision'])
        self.assertEqual((view['state'], workspace.status(root)['gate']), ('waiting', 'deck'),
                         view.get('problem'))
        self.assertTrue(self.built(root)['start']['design'])
        self.assertNotEqual((root / 'deck.pptx').read_bytes(), saved)
        self.assertEqual(workspace.history_file(root, 'deck', old['saved']['sha256'],
                                                '.pptx').read_bytes(), saved)
        self.assertNotIn('redesign', self.record(root)['deck'][''])
        self.assertEqual(self.view(root)['redesign'], [])
        with self.assertRaisesRegex(WorkspaceError, 'not one drawn without a design'):
            self.engine.redesign(root, None)

    def test_visual_12_compatibility_refresh(self):
        self.slides.lacking = ['design-schema-2', 'design-batch', 'json-refusals',
                               'compose-review']
        needs = self.engine.deck_needs(fresh=True)
        names = [slides_tool.NAMES[name] for name in self.slides.lacking]
        self.assertEqual(needs['lacks'], names)
        for words in (*names, f'Update Harness Slides to {slides_tool.RELEASE} or newer from '
                      'Versions on the Status screen', 'A deck already begun carries on'):
            self.assertIn(words, needs['update'])
        self.assertEqual(needs['missing'], [], 'a deck already begun has all it needs')
        [item] = [item for item in needs['items'] if item['id'] == 'deck-slides']
        self.assertEqual((item['state'], item['fix'], item['versions'], item['facts'][1]),
                         ('problem', needs['update'], True,
                          {'label': 'What a new deck needs', 'state': 'problem',
                           'detail': 'missing ' + ', '.join(names)}))
        root = self.begin()
        self.to_end(root)
        view = self.view(root)
        self.assertEqual(view['deck_left']['says'], left(pipeline.DECK_LEFT, needs['update']))
        self.assertEqual(self.kinds().count('outline'), 0, 'no new deck is begun without it')
        # A tool with what a new deck needs is installed, and the person checks again.
        self.slides.lacking, self.slides.design = [], True
        self.engine.look_again()
        view = self.view(root)
        self.assertEqual((view['deck_left'], view['outline']['waiting'],
                          bool(view['outline']['design'])), (None, True, True),
                         'the deck waiting on it is begun, with its design')
        [item] = [item for item in self.engine.deck_needs()['items']
                  if item['id'] == 'deck-slides']
        self.assertEqual((item['state'], item['versions']), ('ok', False))

    def test_a_brand_skill_that_cannot_export_a_brand_for_a_deck_is_said_so(self):
        self.brand.refuse['contracts'] = ['Unknown command: contract.']
        needs = self.engine.deck_needs(fresh=True)
        [item] = [item for item in needs['items'] if item['id'] == 'deck-brand']
        self.assertEqual((item['state'], item['facts'][1]['state']), ('problem', 'problem'))
        self.assertIn('it has no `contract export` and `contract check`', needs['missing'][0])


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


class PageCase(DeckCase):
    """The runner's page, asked as the browser asks it."""

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


class PageTests(PageCase):
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
        self.assertEqual(sorted(shown), ['checked', 'design', 'level', 'note', 'sha256',
                                         'slides', 'waiting', 'worth'])
        self.assertIsNone(shown['design'], 'a tool without a design session: words alone')
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
            'serves': ['O2'], 'design': None})
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


class DesignPageTests(PageCase):
    """The outline gate on the page, with a design proposed beside the words."""

    def setUp(self):
        super().setUp()
        self.slides.design = True

    def test_the_page_shows_how_each_slide_is_drawn_and_sends_the_revision_it_read(self):
        root = self.begin()
        self.to_outline(root)
        run = self.get('run', path=str(root))
        shown = run['outline']
        drawn = shown['slides'][1]['design']
        self.assertEqual(drawn, {
            'claim': OUTLINE['slides'][1]['title'],
            'question': f"Why does it matter that {OUTLINE['slides'][1]['title'].lower()}?",
            'family': 'diagram', 'purpose': 'Show the points as the parts of one mechanism.',
            'drawn': 'Native boxes for each point, joined left to right, the focal statement '
                     'above them.',
            'why': 'The parts and how they connect are spatial, so a diagram shows them.',
            'alternative': {'treatment': 'A list of the points',
                            'reason': 'A list hides how the parts connect.'},
            'asset': {'description': 'Native boxes and connectors.', 'disposition': 'selected',
                      'reason': 'The boxes carry the relation.'},
            'candidates': [{'kind': 'icon', 'ref': 'server', 'concept': 'An instance',
                            'status': 'pending'}], 'keeps': []})
        self.assertEqual(shown['slides'][0]['design']['family'], 'text')
        self.assertIn('Slide 2: the icon "server" for An instance is not resolved yet.',
                      shown['worth'])
        sent = {'path': str(root), 'level': None, 'decision': 'approve', 'note': None,
                'seen': shown['sha256']}
        self.assertIn('has changed since it was opened',
                      self.post('outline', {**sent, 'design': 'f' * 64}, 409)['error'])
        run = self.post('outline', {**sent, 'design': shown['design']['revision']})
        self.assertEqual((run['outline']['waiting'], run['outline']['design']['revision']),
                         (False, None))
        self.assertEqual(self.record(root)['deck']['']['approved']['design']['revision'],
                         shown['design']['revision'])

    def test_a_deck_drawn_without_a_design_is_drawn_again_from_one_only_when_asked(self):
        self.slides.design = False
        root = self.begin()
        self.drawn(root)
        self.slides.design = True
        run = self.get('run', path=str(root))
        self.assertEqual(run['redesign'], [{'level': None, 'artifact': 'deck',
                                            'label': workspace.label('deck'), 'may': True,
                                            'why': None}])
        self.assertIn('Give level as text', self.post('redesign', {'path': str(root),
                                                                   'level': 3}, 400)['error'])
        run = self.post('redesign', {'path': str(root), 'level': None})
        self.assertEqual((run['outline']['waiting'], bool(run['outline']['design']),
                          run['redesign']), (True, True, []))
        self.assertIn('not one drawn without a design',
                      self.post('redesign', {'path': str(root)}, 409)['error'])
        self.assertEqual(self.post('redesign', {'path': str(self.base)}, 403)['error'],
                         'That folder is not a training this computer knows.')


class AssetPageTests(PageCase):
    """A deck waiting for a picture: the run lists what its design uses, and the person
    supplies the picture on the page."""

    def setUp(self):
        super().setUp()
        self.slides.design = self.slides.keeps = True
        self.workers.design_said = with_assets(runner_support.designed(OUTLINE))

    def test_the_run_lists_the_decks_assets_and_a_picture_is_supplied_on_the_page(self):
        import base64
        root = self.begin()
        self.drawn(root)
        run = self.get('run', path=str(root))
        self.assertEqual(run['state'], 'waiting')
        self.assertEqual(run['deck']['assets'], [
            {'asset': 'icon_instance', 'slide': 'what-it-does', 'kind': 'icon', 'ref': 'server',
             'concept': 'An instance', 'state': 'recorded', 'alt': 'Server', 'supply': False},
            {'asset': 'console_view', 'slide': 'what-it-does', 'kind': 'screenshot',
             'ref': 'The restart in the console', 'concept': 'Instances replaced in turn',
             'state': 'wanted', 'alt': None, 'supply': True}])
        sent = {'path': str(root), 'level': None, 'asset': 'console_view',
                'content': base64.b64encode(png(9)).decode(), 'alt': 'The console',
                'source': 'Course author', 'restrictions': None}
        self.assertIn('Say what the picture shows', self.post('asset', {**sent, 'alt': ' '},
                                                               400)['error'])
        self.assertIn('did not arrive whole', self.post('asset', {**sent, 'content': '%%'},
                                                        400)['error'])
        self.assertIn('is not a picture the approved design', self.post(
            'asset', {**sent, 'asset': 'icon_instance'}, 409)['error'])
        run = self.post('asset', sent)
        self.assertIsNone(run['problem'])
        self.assertEqual(workspace.status(root)['gate'], 'deck')
        self.assertEqual(pipeline.recorded(root, None)['console_view']['alt'], 'The console')


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
        expect['deck-outline+design'] = expect['deck-outline']
        expect['deck-section+design'] = expect['deck-section']
        expect['deck-review+design'] = {'list_inputs', 'read_input', 'look_at_slide',
                                        'submit_judgements', 'submit_coverage'}
        for job, tools in expect.items():
            with self.subTest(job):
                text = briefs.guidance(job.partition('+')[0], design=job.endswith('+design'))
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
        judging = briefs.guidance('deck-review', design=True)
        for told in ('`about`: `drawing` when drawing the slide again would put it right and '
                     'keep its approved visual concept and its words', '`concept`',
                     'cite at least one card', 'passes without any picture',
                     'Boxes are not a fault in themselves'):
            self.assertIn(told, judging)
        self.assertNotIn('Ask every question of every slide', judging)
        beyond = briefs.guidance('deck-section', repair=True, design=True, beyond=True)
        self.assertLess(beyond.index('## What drawing cannot put right'),
                        beyond.index('## Hand back'))
        self.assertIn('name the slide in `beyond` when you hand in', beyond)
        self.assertEqual(briefs.guidance('deck-section', repair=True, design=True),
                         beyond.replace('\n' + briefs.read('deck-repair-beyond'), '', 1))
        with self.assertRaises(WorkspaceError):
            briefs.guidance('deck-section', repair=True, beyond=True)

    def test_the_writer_of_a_design_names_icons_by_their_ids_only_where_the_tool_takes_them(self):
        exact = briefs.guidance('deck-outline', design=True, icons=True)
        self.assertEqual(exact, briefs.guidance('deck-outline', design=True).replace(
            '\n## Hand back\n', '\n' + briefs.read('deck-design-icons') + '\n## Hand back\n'))
        for told in ('`search_icons`', '`"refType": "library-id"`',
                     'A picture or a screenshot is still named by what it shows'):
            self.assertIn(told, exact)
        self.assertLess(exact.index('## Icons by their exact ID'), exact.index('## Hand back'))
        with self.assertRaisesRegex(WorkspaceError, 'are told of its design'):
            briefs.guidance('deck-outline', icons=True)

    def test_the_outline_writer_proposes_the_design_only_when_asked_and_before_handing_back(self):
        plain, designed = briefs.guidance('deck-outline'), briefs.guidance('deck-outline',
                                                                           design=True)
        self.assertNotIn('## The design', plain)
        self.assertLess(designed.index('## The design'), designed.index('## Hand back'))
        for told in ('as `design` to `check_outline` and `submit_outline`',
                     'the cover, section and closing slides too', '`takeaway`',
                     '`alternative`', '`visual`', '`composition`', '`candidates`',
                     '`qualifications`', 'Direct text is right', 'is a requirement, not copy',
                     'offers a native diagram instead'):
            self.assertIn(told, designed)
        self.assertNotIn('nothing about how it is drawn', plain)
        with self.assertRaisesRegex(WorkspaceError, 'are told of its design'):
            briefs.guidance('document', design=True)

    def test_a_composer_draws_the_approved_design_and_keeps_the_freedom_of_direct_text(self):
        plain, designed = briefs.guidance('deck-section'), briefs.guidance('deck-section',
                                                                            design=True)
        self.assertEqual(plain, briefs.read('deck-section'), 'without a design, as before')
        for gone in ('whether an icon helps', 'Use an icon only where it names a recognisable '
                     'thing.'):
            self.assertIn(gone, plain)
            self.assertNotIn(gone, designed)
        for told in ("So is each slide's approved design", "Copy each slide's `intent`",
                     'Draw the visual the design approved',
                     'Where it chose direct text, draw text, and add nothing to decorate it',
                     'Place the icons the design names',
                     'Add another only where it names a recognisable thing',
                     'Draw nothing the title does not announce', '`search_icons`'):
            self.assertIn(told, designed)
        self.assertEqual(designed.count('## '), plain.count('## '))
        self.assertLess(designed.index('## How to design'), designed.index('## Hand back'))
        repair, again = (briefs.guidance('deck-section', repair=True),
                         briefs.guidance('deck-section', repair=True, design=True))
        self.assertIn('The words stay as they were approved.', repair)
        self.assertNotIn('approved design', repair)
        for told in ('how a slide is drawn, within its approved design',
                     'another visual concept than the one approved',
                     'The words and the design stay as they were approved.'):
            self.assertIn(told, again)
        self.assertEqual(again.count('## You are drawing this section again'), 1)

    def test_naming_rules_are_told_before_how_to_hand_back(self):
        for job, more in (('document', {}), ('brief', {'kind': 'product'}), ('scenario', {})):
            text = briefs.guidance(job, naming=True, **more)
            self.assertLess(text.index('## Names'), text.index('## Hand back'))
            self.assertIn('It governs names and nothing else', text)
            self.assertNotIn('## Names', briefs.guidance(job, **more))


if __name__ == '__main__':
    import unittest
    unittest.main()
