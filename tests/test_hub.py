"""The team hub, against bare git repositories in temporary directories. No network."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers
import hub
import validate_package
from test_cli import Flow, example, levelled

CLI = helpers.SCRIPTS / 'training.py'
NEVER = {'sources', '.training-studio', '.harness-research', '.harness-slides'}
REPORT = '# Research brief\n\nA rolling restart keeps capacity when an app has two instances.\n'
AUDIENCE = '# Platform leads\n\nThey run forty apps and are short on time.\n'
PLAIN = ['blueprint.md', 'deck.pptx', 'document.docx', 'document.md', 'product-brief.docx',
         'product-brief.md', 'record.json', 'research-report.md', 'scenario.md',
         'yoodli/main.md']
FOUNDED = {}


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.com',
                           *args], cwd=repo, capture_output=True, text=True, check=True)
    return done.stdout.strip()


def tearDownModule():
    if FOUNDED:
        FOUNDED.pop('holder').cleanup()
        FOUNDED.clear()


class HubCase(Flow):
    """A bare repository standing in for the team's remote, and people who each have their
    own data folder, git identity and training directory."""

    def setUp(self):
        super().setUp()
        self.base = self.root.parent
        self.remote = self.base / 'hub.git'
        (self.base / 'no-templates').mkdir()
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE'):
            os.environ.pop(name, None)
        self.be('alex')

    def bare(self, name: str = 'hub.git') -> Path:
        """An empty repository of the kind a host makes: nothing in it, main as its branch."""
        remote = self.base / name
        remote.mkdir()
        git(remote, 'init', '--quiet', '--bare')
        git(remote, 'symbolic-ref', 'HEAD', 'refs/heads/main')
        return remote

    def be(self, person: str, directory: str = 'training') -> None:
        """Act as a person, in one of their directories."""
        folder = self.base / person
        if not folder.is_dir():
            folder.mkdir()
            helpers.gitconfig(
                folder / 'gitconfig',
                f'[user]\n\tname = {person.title()}\n\temail = {person}@example.com\n'
                f"[init]\n\tdefaultBranch = main\n\ttemplateDir = {self.base / 'no-templates'}\n")
        os.environ.update({'TRAINING_STUDIO_DATA': str(folder / 'data'),
                           'GIT_CONFIG_GLOBAL': str(folder / 'gitconfig'),
                           'GIT_CONFIG_NOSYSTEM': '1'})
        self.root = folder / directory
        self.root.mkdir(exist_ok=True)

    def hub(self, *args, expect=0) -> dict:
        return self.cli('hub', *args, expect=expect)

    def join(self, *args, expect=0) -> dict:
        if not self.remote.exists():
            self.bare()
        return self.hub('join', str(self.remote), *args, expect=expect)

    def founded(self, again: bool = False) -> None:
        """Alex has set the hub up as "team" and Blake has joined it.

        That is done through the commands the first time, and whenever `again` asks for it.
        Other tests start from a copy of the result, which is much quicker.
        """
        parts = ('hub.git', 'alex/data', 'blake/data')
        if again or not FOUNDED:
            self.join('--init', '--name', 'team')
            self.be('blake')
            self.join()
            self.be('alex')
            if not FOUNDED:
                FOUNDED.update(holder=tempfile.TemporaryDirectory(), base=str(self.base))
                for part in parts:
                    shutil.copytree(self.base / part, Path(FOUNDED['holder'].name) / part)
            return
        self.be('blake')
        self.be('alex')
        for part in parts:
            shutil.copytree(Path(FOUNDED['holder'].name) / part, self.base / part)
        for person in ('alex', 'blake'):
            data = self.base / person / 'data'
            for path in (data / 'hubs.json', data / 'hubs' / 'team' / '.git' / 'config'):
                path.write_text(path.read_text().replace(FOUNDED['base'], str(self.base)))

    def clone(self, name: str = 'team') -> Path:
        return Path(os.environ['TRAINING_STUDIO_DATA']) / 'hubs' / name

    def tree(self, under: str = '') -> list[str]:
        """Every file on the remote, or those under one folder with the folder left off."""
        paths = git(self.remote, 'ls-tree', '-r', '--name-only', 'main').splitlines()
        return [path[len(under):] for path in paths if path.startswith(under)]

    def shared(self, path: str) -> str:
        return git(self.remote, 'show', f'main:{path}')

    def record(self, revision: int = 1, training: str = 'rolling-restarts') -> dict:
        return json.loads(self.shared(f'trainings/{training}/{revision}/record.json'))

    def start(self, *init_args, title: str = 'Rolling restarts') -> None:
        """A training with approved research and nothing built from it yet."""
        self.cli('init', '--title', title, *init_args)
        self.make('intake', 'intake.md', '# Intake\n\n## Audience\nPlatform leads.\n')
        self.make('research-plan', '.training-studio/research-plan.json',
                  json.dumps(helpers.PLAN))
        self.write('.harness-research/research.json', json.dumps(helpers.RESEARCH))
        self.make('research', '.harness-research/research-report.md', REPORT)

    def lesson(self, level: str | None = None) -> None:
        """An approved blueprint and scenario, for one level or for a plain training."""
        at = f'@{level}' if level else ''
        folder = f'{level}/' if level else ''
        text = example('blueprint.md')
        self.make(f'blueprint{at}', f'{folder}blueprint.md',
                  levelled(text, level) if level else text)
        self.make(f'scenario:main{at}', f'{folder}scenario.md', example('scenario.md'))

    def small(self, *init_args, title: str = 'Rolling restarts') -> None:
        self.start(*init_args, title=title)
        self.lesson()


class JoinTests(HubCase):
    def test_a_repository_without_the_layout_is_refused(self):
        refusal = self.join(expect=2)['error']
        self.assertIn('hub.json', refusal)
        self.assertIn('--init', refusal)
        self.assertEqual(self.hub('list'), {'hubs': []})
        self.assertEqual(list((self.clone().parent).iterdir()), [])

    def test_init_lays_out_an_empty_repository_and_shares_it(self):
        joined = self.join('--init', '--name', 'team')
        self.assertEqual((joined['hub'], joined['initialised'], joined['pushed']),
                         ('team', True, True))
        self.assertEqual(self.tree(), ['README.md', 'hub.json'])
        self.assertEqual(json.loads(self.shared('hub.json')), {'schema': 1, 'name': 'team'})
        self.assertIn('# team', self.shared('README.md'))
        listed = self.hub('list')['hubs']
        self.assertEqual([(item['name'], item['pushed'], item['unpushed']) for item in listed],
                         [('team', True, 0)])
        self.assertEqual(listed[0]['url'], str(self.remote))

    def test_without_a_name_a_new_hub_is_named_after_its_address(self):
        self.assertEqual(self.join('--init')['hub'], 'hub')

    def test_init_refuses_a_repository_that_already_holds_something_else(self):
        seed = self.base / 'seed'
        git(self.base, 'clone', '--quiet', str(self.bare()), str(seed))
        (seed / 'notes.md').write_text('Not a hub.\n')
        git(seed, 'add', '-A')
        git(seed, 'commit', '--quiet', '-m', 'notes')
        git(seed, 'push', '--quiet', 'origin', 'HEAD:refs/heads/main')
        self.assertIn('already has files', self.join('--init', expect=2)['error'])
        self.assertEqual(self.tree(), ['notes.md'])
        self.assertIn('not a hub', self.join(expect=2)['error'])

    def test_a_second_person_joins_under_the_name_the_hub_gives_itself(self):
        self.join('--init', '--name', 'team')
        self.be('blake')
        joined = self.join()
        self.assertEqual((joined['hub'], joined['initialised']), ('team', False))
        self.assertTrue((self.clone() / 'hub.json').is_file())
        self.assertEqual(self.join('--name', 'field')['hub'], 'field')
        self.assertEqual([item['name'] for item in self.hub('list')['hubs']],
                         ['field', 'team'])

    def test_init_on_a_repository_that_is_already_a_hub_just_joins_it(self):
        self.join('--init', '--name', 'team')
        self.be('blake')
        self.assertEqual(self.join('--init')['initialised'], False)
        self.assertEqual(self.tree(), ['README.md', 'hub.json'])

    def test_two_people_setting_up_one_empty_repository_end_with_one_hub(self):
        self.bare()
        real, raced = hub.run, []

        def racing(repo, *args):
            if args[0] == 'push' and not raced:
                raced.append(True)
                self.be('blake')
                self.assertTrue(self.join('--init', '--name', 'ours')['pushed'])
                self.be('alex')
            return real(repo, *args)

        with mock.patch.object(hub, 'run', racing):
            joined = self.join('--init', '--name', 'team')
        self.assertEqual((joined['hub'], joined['pushed']), ('team', True))
        self.assertEqual(json.loads(self.shared('hub.json')), {'schema': 1, 'name': 'ours'})
        self.assertEqual(self.tree(), ['README.md', 'hub.json'])
        self.assertIn('# ours', self.shared('README.md'))
        self.assertEqual(git(self.clone(), 'status', '--porcelain'), '')

    def test_a_local_copy_keeps_files_byte_for_byte_and_checks_out_no_links(self):
        self.join('--init', '--name', 'team')
        self.assertEqual(git(self.clone(), 'config', '--local', 'core.autocrlf'), 'false')
        self.assertEqual(git(self.clone(), 'config', '--local', 'core.symlinks'), 'false')

    def test_a_name_that_is_taken_is_refused(self):
        self.join('--init', '--name', 'team')
        self.assertIn('already joined', self.join(expect=2)['error'])
        self.assertIn('already joined', self.join('--name', 'team', expect=2)['error'])

    def test_bad_names_and_addresses_are_refused(self):
        self.assertIn('lowercase', self.join('--name', 'Team Hub', expect=2)['error'])
        secret = self.hub('join', 'https://someone:s3cret@example.com/team/hub.git', expect=2)
        self.assertIn('password or token', secret['error'])
        self.assertNotIn('s3cret', json.dumps(self.hub('list')))
        token = 'tok_' + 'a1B2' * 9
        alone = self.hub('join', f'https://{token}@example.com/team/hub.git', expect=2)
        self.assertIn('password or token', alone['error'])
        self.assertNotIn(token, json.dumps(self.hub('list')))
        missing = self.hub('join', str(self.base / 'nowhere.git'), expect=2)
        self.assertIn('Could not clone', missing['error'])
        self.assertEqual(self.hub('list'), {'hubs': []})

    def test_list_says_when_a_local_copy_has_gone_and_joining_again_restores_it(self):
        self.founded()
        shutil.rmtree(self.clone())
        listed = self.hub('list')['hubs'][0]
        self.assertEqual((listed['name'], listed['pushed']), ('team', False))
        self.assertIn('missing', listed['notice'])
        self.assertIn('No hub called "team" is joined', self.hub('sync', expect=2)['error'])
        self.assertEqual(self.join()['hub'], 'team')
        self.assertTrue(self.hub('list')['hubs'][0]['pushed'])

    def test_a_layout_from_a_newer_version_is_refused(self):
        self.join('--init', '--name', 'team')
        (self.clone() / 'hub.json').write_text('{"schema": 2, "name": "team"}')
        git(self.clone(), 'commit', '--quiet', '-am', 'A newer layout')
        git(self.clone(), 'push', '--quiet', 'origin', 'HEAD:refs/heads/main')
        self.assertIn('Update the skill', self.hub('find', expect=2)['error'])
        self.be('blake')
        self.assertIn('Update the skill', self.join(expect=2)['error'])
        self.assertEqual(self.hub('list'), {'hubs': []})


class ChoosingTests(HubCase):
    def test_use_makes_a_joined_hub_the_one_a_training_publishes_to(self):
        self.founded()
        other = self.bare('field.git')
        self.hub('join', str(other), '--init', '--name', 'field')
        self.small()
        choose = self.hub('publish', expect=2)['error']
        self.assertIn('Several hubs are joined: field, team', choose)
        self.assertIn('hub use', choose)
        self.assertEqual(self.hub('use', 'field'), {'hub': 'field',
                                                    'training': 'rolling-restarts'})
        self.assertEqual(json.loads((self.root / '.training-studio' / 'hub.json').read_text()),
                         {'schema': 1, 'hub': 'field'})
        self.assertEqual(self.hub('publish')['hub'], 'field')
        self.assertEqual(self.tree(), ['README.md', 'hub.json'])
        chosen = {item['name']: item['chosen'] for item in self.hub('list')['hubs']}
        self.assertEqual(chosen, {'field': True, 'team': False})

    def test_use_needs_a_training_and_a_hub_that_is_joined(self):
        self.founded()
        self.assertIn('No training', self.hub('use', 'team', expect=2)['error'])
        self.cli('init', '--title', 'Topic')
        self.assertIn('No hub called "field"', self.hub('use', 'field', expect=2)['error'])

    def test_the_only_joined_hub_is_used_and_remembered(self):
        self.founded()
        self.small()
        self.assertEqual(self.hub('status')['hub'], 'team')
        self.assertFalse((self.root / '.training-studio' / 'hub.json').exists())
        self.hub('publish')
        self.assertEqual(json.loads((self.root / '.training-studio' / 'hub.json').read_text()),
                         {'schema': 1, 'hub': 'team'})

    def test_without_a_hub_the_commands_say_how_to_get_one(self):
        self.small()
        self.assertIn('hub join', self.hub('publish', expect=2)['error'])
        self.assertIn('hub join', self.hub('find', expect=2)['error'])
        status = self.hub('status')
        self.assertEqual((status['hub'], status['revision']), (None, None))
        self.assertIn('hub join', status['notice'])

    def test_a_training_whose_hub_was_never_joined_here_says_so(self):
        self.founded()
        self.small()
        self.hub('use', 'team')
        self.be('casey')
        self.root = self.base / 'alex' / 'training'
        self.assertIn('No hub called "team" is joined', self.hub('publish', expect=2)['error'])


class PublishTests(HubCase):
    def test_a_finished_training_is_published_as_revision_one(self):
        self.founded()
        self.research()
        self.complete()
        result = self.hub('publish', '--message', 'First cut')
        self.assertEqual((result['hub'], result['training'], result['revision']),
                         ('team', 'rolling-restarts', 1))
        self.assertEqual((result['created'], result['pushed'], result['ready']),
                         (True, True, True))
        self.assertIsNone(result['notice'])
        self.assertEqual(self.tree('trainings/rolling-restarts/1/'), PLAIN)
        self.assertEqual(sorted([entry['path'] for entry in result['files']] + ['record.json']),
                         PLAIN)
        record = self.record()
        self.assertEqual((record['title'], record['levels'], record['published_by']),
                         ('Rolling restarts', [], 'Alex'))
        self.assertEqual((record['training'], record['revision'], record['ready']),
                         ('rolling-restarts', 1, True))
        self.assertEqual(record['message'], 'First cut')
        self.assertRegex(record['published_at'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$')
        self.assertIn('guidance', record)
        by_path = {entry['path']: entry for entry in record['files']}
        self.assertEqual(sorted(by_path), [path for path in PLAIN if path != 'record.json'])
        for path, entry in by_path.items():
            self.assertEqual(entry['sha256'], hub.workspace.sha256_file(self.root / path), path)
        self.assertEqual((by_path['document.md']['artifact'], by_path['document.md']['export']),
                         ('document', False))
        self.assertEqual((by_path['document.docx']['artifact'],
                          by_path['document.docx']['export']), ('document', True))
        self.assertEqual(by_path['research-report.md']['artifact'], 'research')
        self.assertEqual(by_path['yoodli/main.md']['artifact'], 'yoodli:main')
        self.assertIn('Publish rolling-restarts: First cut',
                      git(self.remote, 'log', '--format=%s', 'main'))

    def test_the_result_says_what_was_left_out_and_why(self):
        self.founded()
        self.research()
        self.complete()
        left = {(item['artifact'], item['reason']) for item in self.hub('publish')['left_out']}
        self.assertIn(('intake', 'It is not part of a published training.'), left)
        self.assertIn(('research-plan', 'It is not part of a published training.'), left)
        self.assertIn(('yoodli:main', 'Its export is missing.'), left)

    def test_sources_and_bookkeeping_are_never_published(self):
        self.founded()
        self.research()
        self.complete()
        self.write('sources/customer-notes.md', 'PRIVATE customer notes\n')
        self.write('.harness-slides/task.json', '{"private": true}')
        self.write('deck-handoff.md', 'A note for the deck builder.\n')
        self.write('sources/document.docx', 'exported document')
        self.cli('export', 'document', '--file', 'sources/document.docx')
        self.assertEqual(self.cli('status')['exports']['document'], 'current')
        result = self.hub('publish')
        ever = set(git(self.remote, 'log', '--all', '--format=', '--name-only').split())
        self.assertTrue(ever)
        for path in ever | set(git(self.clone(), 'ls-files').split()):
            self.assertFalse(NEVER & set(path.split('/')), path)
        self.assertNotIn('trainings/rolling-restarts/1/intake.md', ever)
        self.assertNotIn('trainings/rolling-restarts/1/deck-handoff.md', ever)
        self.assertNotIn('trainings/rolling-restarts/1/document.docx', ever)
        self.assertIn({'artifact': 'document', 'file': 'sources/document.docx',
                       'reason': 'It is under sources/, which is never published.'},
                      result['left_out'])
        grep = subprocess.run(['git', 'grep', '-l', 'PRIVATE', 'main'], cwd=self.remote,
                              capture_output=True, text=True)
        self.assertEqual((grep.returncode, grep.stdout), (1, ''))

    def test_only_approved_artifacts_are_published(self):
        self.founded()
        self.research()
        self.complete()
        self.write('document.md', example('document.md') + '\nAn edit nobody approved.\n')
        self.assertEqual(self.cli('status')['artifacts']['document'], 'draft')
        result = self.hub('publish')
        published = self.tree('trainings/rolling-restarts/1/')
        for path in ('document.md', 'document.docx', 'deck.pptx'):
            self.assertNotIn(path, published)
        self.assertIn('product-brief.md', published)
        self.assertFalse(result['ready'])
        self.assertIn('not ready', result['notice'])
        self.assertFalse(self.record()['ready'])
        reasons = {item['artifact']: item['reason'] for item in result['left_out']}
        self.assertEqual(reasons['document'], 'It is draft; only approved work is published.')
        self.assertEqual(reasons['deck'], 'It is stale; only approved work is published.')

    def test_publishing_refuses_when_nothing_is_approved(self):
        self.founded()
        self.cli('init', '--title', 'Rolling restarts')
        self.write('blueprint.md', example('blueprint.md'))
        self.write('scenario.md', example('scenario.md'))
        self.assertIn('Nothing in this training is approved',
                      self.hub('publish', expect=2)['error'])
        self.make('intake', 'intake.md', '# Intake\n')
        self.assertIn('Nothing in this training is approved',
                      self.hub('publish', expect=2)['error'])
        self.assertEqual(self.tree(), ['README.md', 'hub.json'])
        self.assertEqual(git(self.clone(), 'status', '--porcelain'), '')

    def test_publishing_again_makes_the_next_revision_and_leaves_the_first_alone(self):
        self.founded()
        self.small()
        self.hub('publish')
        first = git(self.remote, 'rev-parse', 'main:trainings/rolling-restarts/1')
        self.write('scenario.md', example('scenario.md') + '\nA second thought.\n')
        self.cli('approve', 'scenario:main')
        result = self.hub('publish')
        self.assertEqual((result['revision'], result['created'], result['pushed']),
                         (2, True, True))
        self.assertEqual(git(self.remote, 'rev-parse', 'main:trainings/rolling-restarts/1'),
                         first)
        self.assertNotIn('A second thought.',
                         self.shared('trainings/rolling-restarts/1/scenario.md'))
        self.assertIn('A second thought.',
                      self.shared('trainings/rolling-restarts/2/scenario.md'))
        self.assertEqual(self.record(2)['revision'], 2)

    def test_publishing_unchanged_work_makes_no_new_revision(self):
        self.founded()
        self.small()
        self.hub('publish')
        again = self.hub('publish')
        self.assertEqual((again['revision'], again['created'], again['pushed']),
                         (1, False, True))
        self.assertIn('Nothing has changed since revision 1', again['notice'])
        self.assertEqual(self.tree('trainings/rolling-restarts/'),
                         ['1/blueprint.md', '1/record.json', '1/research-report.md',
                          '1/scenario.md'])

    def test_becoming_ready_is_worth_a_revision_of_its_own(self):
        self.founded()
        self.research()
        self.complete()
        self.cli('checkpoint', '--question', 'Is the timeout section right?')
        self.assertEqual(self.hub('publish')['ready'], False)
        self.cli('checkpoint', '--no-question')
        result = self.hub('publish')
        self.assertEqual((result['revision'], result['created'], result['ready']),
                         (2, True, True))
        self.assertEqual((self.record(1)['ready'], self.record(2)['ready']), (False, True))
        self.assertEqual(self.tree('trainings/rolling-restarts/1/'),
                         self.tree('trainings/rolling-restarts/2/'))
        self.assertIn('| 2 | ', self.shared('README.md'))

    def test_the_training_index_is_published_when_there_is_one(self):
        self.founded()
        self.small()
        self.write('README.md', '# Rolling restarts\n\nThe index of this training.\n')
        self.hub('publish')
        self.assertIn('The index of this training.',
                      self.shared('trainings/rolling-restarts/1/README.md'))
        entry = next(item for item in self.record()['files'] if item['path'] == 'README.md')
        self.assertEqual((entry['artifact'], entry['export']), (None, False))

    def test_a_file_behind_a_symbolic_link_is_not_published(self):
        self.founded()
        self.research()
        self.content()
        outside = self.base / 'elsewhere.docx'
        outside.write_text('exported document')
        (self.root / 'document.docx').unlink()
        (self.root / 'document.docx').symlink_to(outside)
        self.assertEqual(self.cli('status')['exports']['document'], 'current')
        result = self.hub('publish')
        self.assertNotIn('document.docx', self.tree('trainings/rolling-restarts/1/'))
        self.assertIn({'artifact': 'document', 'file': 'document.docx',
                       'reason': 'It is a symbolic link, or sits behind one.'},
                      result['left_out'])

    def test_a_link_planted_where_new_work_goes_is_not_written_through(self):
        self.founded()
        self.small()
        elsewhere = self.base / 'elsewhere'
        elsewhere.mkdir()
        for folder, command in (('trainings', ('publish',)),
                                ('scenarios', ('share', 'scenario', 'main'))):
            (self.clone() / folder).symlink_to(elsewhere, target_is_directory=True)
            self.assertIn('symbolic link', self.hub(*command, expect=2)['error'])
            (self.clone() / folder).unlink()
        self.assertEqual(list(elsewhere.iterdir()), [])
        self.assertEqual(sorted(path.name for path in self.clone().parent.iterdir()
                                if path.name.startswith('.publishing')), [])
        self.assertEqual(self.hub('publish')['revision'], 1)

    def test_publishing_needs_a_git_identity(self):
        self.founded()
        self.small()
        nobody = helpers.gitconfig(self.base / 'nobody.gitconfig',
                                   '[user]\n\tuseConfigOnly = true\n')
        os.environ['GIT_CONFIG_GLOBAL'] = str(nobody)
        self.assertIn('git does not know who you are', self.hub('publish', expect=2)['error'])
        self.assertEqual(git(self.clone(), 'status', '--porcelain'), '')
        self.assertFalse((self.clone() / 'trainings').exists())


class LevelTests(HubCase):
    def test_each_level_is_published_in_its_own_folder(self):
        self.founded()
        self.research('--levels', '101,301')
        self.complete('101')
        self.complete('301')
        result = self.hub('publish')
        self.assertTrue(result['ready'])
        expected = sorted(['record.json', 'research-report.md']
                          + [f'{level}/{path}' for level in ('101', '301') for path in PLAIN
                             if path not in ('record.json', 'research-report.md')])
        self.assertEqual(self.tree('trainings/rolling-restarts/1/'), expected)
        record = self.record()
        self.assertEqual(record['levels'], ['101', '301'])
        names = {entry['path']: entry['artifact'] for entry in record['files']}
        self.assertEqual(names['101/blueprint.md'], 'blueprint@101')
        self.assertEqual(names['301/scenario.md'], 'scenario:main@301')
        self.assertEqual(names['301/yoodli/main.md'], 'yoodli:main@301')
        self.assertEqual(names['301/product-brief.docx'], 'brief@301')

    def test_a_level_that_is_not_approved_yet_stays_behind(self):
        self.founded()
        self.start('--levels', '101,301')
        self.lesson('101')
        self.write('301/blueprint.md', levelled(example('blueprint.md'), '301'))
        self.cli('save', 'blueprint@301', '--built')
        result = self.hub('publish')
        self.assertEqual(self.tree('trainings/rolling-restarts/1/'),
                         ['101/blueprint.md', '101/scenario.md', 'record.json',
                          'research-report.md'])
        reasons = {item['artifact']: item['reason'] for item in result['left_out']}
        self.assertEqual(reasons['blueprint@301'],
                         'It is draft; only approved work is published.')
        self.assertEqual(reasons['document@101'],
                         'It is not-started; only approved work is published.')
        self.assertFalse(result['ready'])

    def test_scenarios_move_between_levelled_trainings(self):
        self.founded()
        self.start('--levels', '101,301')
        self.lesson('101')
        self.write('301/scenarios/outage.md', example('scenario.md'))
        self.cli('save', 'scenario:outage@301')
        self.cli('approve', 'scenario:outage@301')
        self.assertIn('--level', self.hub('share', 'scenario', 'main', expect=2)['error'])
        self.assertEqual(self.hub('share', 'scenario', 'main', '--level', '101')['id'],
                         'rolling-restarts-101')
        self.assertEqual(self.hub('share', 'scenario', 'outage', '--level', '301')['id'],
                         'outage')
        self.hub('publish')
        about = json.loads(self.shared('scenarios/rolling-restarts-101.json'))
        self.assertEqual((about['training'], about['level'], about['scenario']),
                         ('rolling-restarts', '101', 'main'))

        self.be('blake')
        self.hub('sync')
        self.cli('init', '--title', 'Blue-green deploys', '--levels', '201,401')
        self.assertIn('--level', self.hub('get', 'scenario', 'outage', expect=2)['error'])
        self.assertIn('--level', self.hub('get', 'scenario', 'outage', '--level', '101',
                                          expect=2)['error'])
        got = self.hub('get', 'scenario', 'outage', '--level', '401')
        self.assertEqual((got['artifact'], got['file']),
                         ('scenario:outage@401', '401/scenarios/outage.md'))
        got = self.hub('get', 'scenario', 'rolling-restarts/main@101', '--level', '201')
        self.assertEqual((got['artifact'], got['file']), ('scenario:main@201',
                                                          '201/scenario.md'))
        self.assertEqual((self.root / '201' / 'scenario.md').read_text(),
                         example('scenario.md'))
        found = self.cli('status')['scenarios']['found']
        self.assertEqual(sorted(found), ['scenario:main@201', 'scenario:outage@401'])


class SyncTests(HubCase):
    def test_an_unreachable_remote_leaves_the_publish_here_and_says_so(self):
        self.founded()
        self.small()
        away = self.base / 'away.git'
        self.remote.rename(away)
        result = self.hub('publish')
        self.assertEqual((result['created'], result['pushed'], result['revision']),
                         (True, False, 1))
        self.assertIn('could not be reached', result['notice'])
        self.assertIn('not shared yet', result['notice'])
        self.assertEqual(git(self.clone(), 'status', '--porcelain'), '')
        self.assertEqual(git(self.clone(), 'log', '-1', '--format=%s'),
                         'Publish rolling-restarts')
        listed = self.hub('list')['hubs'][0]
        self.assertEqual((listed['pushed'], listed['unpushed']), (False, 1))
        status = self.hub('status')
        self.assertEqual((status['revision'], status['pushed']), (1, False))
        still = self.hub('sync')
        self.assertEqual((still['pushed'], still['reached'], still['unpushed']),
                         (False, False, 1))
        self.assertIn('not shared yet', still['notice'])
        again = self.hub('publish')
        self.assertEqual((again['created'], again['pushed'], again['revision']),
                         (False, False, 1))
        self.assertIn('not shared yet', again['notice'])

        away.rename(self.remote)
        self.assertEqual(self.tree(), ['README.md', 'hub.json'])
        sent = self.hub('sync')
        self.assertEqual((sent['pushed'], sent['unpushed'], sent['notice']), (True, 0, None))
        self.assertIn('trainings/rolling-restarts/1/record.json', self.tree())
        self.assertTrue(self.hub('status')['pushed'])
        self.assertTrue(self.hub('list')['hubs'][0]['pushed'])

    def test_out_of_reach_with_nothing_waiting_says_the_copy_may_be_out_of_date(self):
        self.founded()
        self.small()
        self.hub('publish')
        synced = self.hub('list')['hubs'][0]['synced_at']
        self.remote.rename(self.base / 'away.git')
        quiet = self.hub('sync')
        self.assertEqual((quiet['reached'], quiet['unpushed'], quiet['pushed']),
                         (False, 0, True))
        self.assertIn('could not be reached', quiet['notice'])
        self.assertIn('may be out of date', quiet['notice'])
        self.assertNotIn('not shared yet', quiet['notice'])
        self.assertEqual(quiet['synced_at'], synced)
        again = self.hub('publish')
        self.assertEqual((again['created'], again['pushed']), (False, True))
        self.assertIn('could not be reached', again['notice'])

    def test_a_remote_that_does_not_answer_in_time_counts_as_out_of_reach(self):
        self.founded()
        self.small()
        real = subprocess.run

        def slow(command, **options):
            if command[1] in ('fetch', 'push'):
                raise subprocess.TimeoutExpired(command, options['timeout'])
            return real(command, **options)

        with mock.patch.object(hub.subprocess, 'run', slow):
            result = self.hub('publish')
        self.assertEqual((result['created'], result['pushed']), (True, False))
        self.assertIn('could not be reached (git fetch did not finish in 120 seconds)',
                      result['notice'])
        self.assertIn('not shared yet', result['notice'])
        self.assertTrue(self.hub('sync')['pushed'])

    def test_a_remote_that_refuses_the_push_is_not_reported_as_shared(self):
        self.founded()
        self.small()
        hook = self.remote / 'hooks' / 'pre-receive'
        hook.parent.mkdir(exist_ok=True)
        hook.write_text('#!/bin/sh\necho "this branch is protected" >&2\nexit 1\n')
        hook.chmod(0o755)
        result = self.hub('publish')
        self.assertEqual((result['pushed'], result['created']), (False, True))
        self.assertIn('did not accept', result['notice'])
        self.assertIn('this branch is protected', result['notice'])
        self.assertIn('not shared yet', result['notice'])
        self.assertEqual(self.hub('share', 'scenario', 'main')['pushed'], False)
        self.assertEqual(self.tree(), ['README.md', 'hub.json'])
        hook.unlink()
        self.assertTrue(self.hub('sync')['pushed'])
        self.assertIn('trainings/rolling-restarts/1/record.json', self.tree())

    def test_two_people_publishing_at_once_get_consecutive_revisions(self):
        self.founded()
        self.small()
        self.be('blake')
        self.small()
        first = self.hub('publish')
        theirs = git(self.remote, 'rev-parse', 'main:trainings/rolling-restarts/1')
        self.be('alex')
        second = self.hub('publish')
        self.assertEqual((first['revision'], first['pushed']), (1, True))
        self.assertEqual((second['revision'], second['pushed'], second['created']),
                         (2, True, True))
        self.assertEqual(second['renumbered'],
                         [{'training': 'rolling-restarts', 'from': 1, 'to': 2}])
        self.assertEqual([(self.record(number)['revision'], self.record(number)['published_by'])
                          for number in (1, 2)], [(1, 'Blake'), (2, 'Alex')])
        self.assertEqual(git(self.remote, 'rev-parse', 'main:trainings/rolling-restarts/1'),
                         theirs)
        self.assertEqual(self.tree('trainings/rolling-restarts/2/'),
                         ['blueprint.md', 'record.json', 'research-report.md', 'scenario.md'])
        self.assertEqual(git(self.clone(), 'status', '--porcelain'), '')
        self.assertEqual(self.hub('status')['revision'], 2)

    def test_a_push_that_loses_the_race_is_retried_on_top_of_the_winner(self):
        self.founded()
        self.small()
        self.be('blake')
        self.small()
        real, raced = hub.run, []

        def racing(repo, *args):
            if args[0] == 'push' and not raced:
                raced.append(True)
                self.be('alex')
                self.assertEqual(self.hub('publish')['revision'], 1)
                self.be('blake')
            return real(repo, *args)

        with mock.patch.object(hub, 'run', racing):
            result = self.hub('publish')
        self.assertEqual(raced, [True])
        self.assertEqual((result['revision'], result['pushed']), (2, True))
        self.assertEqual([self.record(number)['published_by'] for number in (1, 2)],
                         ['Alex', 'Blake'])

    def test_revisions_made_while_out_of_reach_are_renumbered_in_order(self):
        self.founded()
        self.small()
        away = self.base / 'away.git'
        self.remote.rename(away)
        self.hub('publish')
        self.write('scenario.md', example('scenario.md') + '\nA second thought.\n')
        self.cli('approve', 'scenario:main')
        self.assertEqual(self.hub('publish')['revision'], 2)
        away.rename(self.remote)
        self.be('blake')
        self.small()
        self.hub('publish')
        self.be('alex')
        sent = self.hub('sync')
        self.assertTrue(sent['pushed'])
        self.assertEqual(sent['renumbered'],
                         [{'training': 'rolling-restarts', 'from': 1, 'to': 2},
                          {'training': 'rolling-restarts', 'from': 2, 'to': 3}])
        self.assertEqual([(self.record(number)['revision'], self.record(number)['published_by'])
                          for number in (1, 2, 3)], [(1, 'Blake'), (2, 'Alex'), (3, 'Alex')])
        self.assertNotIn('A second thought.',
                         self.shared('trainings/rolling-restarts/2/scenario.md'))
        self.assertIn('A second thought.',
                      self.shared('trainings/rolling-restarts/3/scenario.md'))

    def test_nothing_is_forced_and_the_remote_history_only_grows(self):
        self.bare()
        git(self.remote, 'config', 'receive.denyNonFastForwards', 'true')
        git(self.remote, 'config', 'receive.denyDeletes', 'true')
        real, calls, tips = hub.run, [], []

        def recording(repo, *args):
            calls.append(args)
            return real(repo, *args)

        def tip() -> None:
            tips.append(git(self.remote, 'rev-parse', 'main'))

        with mock.patch.object(hub, 'run', recording):
            self.founded(again=True)
            tip()
            self.small()
            self.be('blake')
            self.small()
            self.hub('publish')
            tip()
            self.hub('share', 'scenario', 'main')
            tip()
            self.be('alex')
            self.hub('publish')
            tip()
            self.hub('share', 'scenario', 'main', '--as', 'objection')
            tip()
        pushes = [args for args in calls if args[0] == 'push']
        self.assertGreaterEqual(len(pushes), 5)
        for args in calls:
            self.assertFalse([arg for arg in args if 'force' in arg or arg.startswith('+')
                              or arg in ('-f', '--mirror', '--delete', '--amend')], args)
            self.assertNotIn(args[0], ('reset', 'filter-branch', 'gc', 'prune'), args)
        self.assertEqual(len(set(tips)), len(tips))
        for older, newer in zip(tips, tips[1:]):
            git(self.remote, 'merge-base', '--is-ancestor', older, newer)

    def test_the_index_is_rebuilt_from_what_the_hub_holds(self):
        self.founded()
        self.small()
        self.hub('publish')
        self.hub('share', 'scenario', 'main', '--as', 'objection')
        self.hub('share', 'audience', 'platform-leads', '--file',
                 str(self.write('audience.md', AUDIENCE)))
        self.be('blake')
        self.small(title='Blue-green | deploys')
        self.hub('publish')
        index = self.shared('README.md')
        self.assertIn('| [Rolling restarts](trainings/rolling-restarts/1/) | none | 1 |', index)
        self.assertIn('| [Blue-green \\| deploys](trainings/blue-green-deploys/1/) |', index)
        self.assertIn('by Alex', index)
        self.assertIn('by Blake', index)
        self.assertIn('[The zero-downtime objection](scenarios/objection.md)', index)
        self.assertIn('[Platform leads](audiences/platform-leads.md)', index)
        self.assertEqual(index + '\n', (self.clone() / 'README.md').read_text())
        self.assertEqual(self.hub('sync')['pushed'], True)
        self.assertEqual(self.shared('README.md'), index)

    def test_sync_brings_in_what_teammates_shared(self):
        self.founded()
        self.small()
        self.hub('publish')
        self.be('blake')
        self.assertEqual(self.hub('find')['found'], [])
        received = self.hub('sync')
        self.assertEqual((received['pushed'], received['received'], received['unpushed']),
                         (True, 1, 0))
        self.assertEqual([item['id'] for item in self.hub('find', '--kind', 'training')['found']],
                         ['rolling-restarts'])
        self.assertIsNotNone(self.hub('list')['hubs'][0]['synced_at'])

    def test_sync_sends_changes_made_by_hand_in_the_local_copy(self):
        self.founded()
        (self.clone() / 'audiences').mkdir()
        (self.clone() / 'audiences' / 'executives.md').write_text('# Executives\n')
        listed = self.hub('list')['hubs'][0]
        self.assertEqual((listed['pushed'], listed['uncommitted']), (False, True))
        self.assertTrue(self.hub('sync', 'team')['pushed'])
        self.assertIn('audiences/executives.md', self.tree())
        self.assertIn('[Executives](audiences/executives.md)', self.shared('README.md'))

    def test_a_conflict_it_does_not_understand_is_left_for_the_user(self):
        self.founded()
        (self.clone() / 'NOTES.md').write_text('Alex was here.\n')
        self.hub('sync')
        self.be('blake')
        (self.clone() / 'NOTES.md').write_text('Blake was here.\n')
        refusal = self.hub('sync', expect=2)['error']
        self.assertIn('NOTES.md', refusal)
        self.assertIn(str(self.clone()), refusal)
        self.assertFalse((self.clone() / '.git' / 'rebase-merge').exists())
        self.assertEqual((self.clone() / 'NOTES.md').read_text(), 'Blake was here.\n')
        self.assertEqual(git(self.clone(), 'status', '--porcelain'), '')
        self.assertEqual(self.shared('NOTES.md'), 'Alex was here.')
        self.assertFalse(self.hub('list')['hubs'][0]['pushed'])

    def test_one_command_at_a_time_works_on_a_hub(self):
        self.founded()
        with hub.locked('team'):
            self.assertIn('Another Training Studio command is running',
                          self.hub('sync', expect=2)['error'])
        self.assertTrue(self.hub('sync')['pushed'])

    def test_sync_names_the_hub_or_uses_the_only_one(self):
        self.founded()
        self.assertEqual(self.hub('sync')['hub'], 'team')
        self.assertIn('No hub called "field"', self.hub('sync', 'field', expect=2)['error'])


class StatusTests(HubCase):
    def test_status_says_what_is_published_and_what_has_changed_since(self):
        self.founded()
        self.small()
        before = self.hub('status')
        self.assertEqual((before['hub'], before['training'], before['revision']),
                         ('team', 'rolling-restarts', None))
        self.assertTrue(before['changed'])
        self.assertEqual(before['changes']['added'],
                         ['blueprint.md', 'research-report.md', 'scenario.md'])
        self.hub('publish')
        after = self.hub('status')
        self.assertEqual((after['revision'], after['published_by'], after['pushed']),
                         (1, 'Alex', True))
        self.assertEqual((after['changed'], after['changes']),
                         (False, {'added': [], 'changed': [], 'removed': []}))

        self.write('scenario.md', example('scenario.md') + '\nAn unapproved edit.\n')
        self.assertEqual(self.hub('status')['changes'],
                         {'added': [], 'changed': [], 'removed': ['scenario.md']})
        self.cli('approve', 'scenario:main')
        self.make('scenario:second', 'scenarios/second.md', example('scenario.md'))
        changed = self.hub('status')
        self.assertTrue(changed['changed'])
        self.assertEqual(changed['changes'], {'added': ['scenarios/second.md'],
                                              'changed': ['scenario.md'], 'removed': []})

    def test_status_needs_a_training(self):
        self.founded()
        self.assertIn('No training', self.hub('status', expect=2)['error'])


class FindTests(HubCase):
    def stock(self) -> None:
        """Alex fills the hub; Blake has an up-to-date copy and an empty directory."""
        self.founded()
        self.small()
        self.write('scenarios/audit.md', example('scenario.md').replace(
            '# Scenario: The zero-downtime objection', '# Scenario: The audit question'))
        self.cli('save', 'scenario:audit')
        self.cli('approve', 'scenario:audit')
        self.hub('publish')
        self.hub('share', 'scenario', 'audit')
        self.hub('share', 'audience', 'platform-leads', '--file',
                 str(self.write('audience.md', AUDIENCE)))
        self.be('blake')
        self.hub('sync')

    def test_find_lists_everything_when_there_is_no_query(self):
        self.stock()
        result = self.hub('find')
        self.assertEqual(result['hub'], 'team')
        self.assertIsNotNone(result['synced_at'])
        self.assertEqual([(item['kind'], item['id']) for item in result['found']],
                         [('training', 'rolling-restarts'),
                          ('scenario', 'audit'),
                          ('scenario', 'rolling-restarts/audit'),
                          ('scenario', 'rolling-restarts/main'),
                          ('audience', 'platform-leads')])
        training = result['found'][0]
        self.assertEqual((training['title'], training['revision'], training['published_by']),
                         ('Rolling restarts', 1, 'Alex'))
        self.assertEqual((training['research'], training['ready'], training['levels']),
                         (True, False, []))
        self.assertEqual(training['scenarios'],
                         ['rolling-restarts/audit', 'rolling-restarts/main'])
        self.assertTrue(Path(training['path'], 'blueprint.md').is_file())
        shared = result['found'][1]
        self.assertEqual((shared['title'], shared['shared_by'], shared['training']),
                         ('The audit question', 'Alex', 'rolling-restarts'))
        self.assertEqual(result['found'][4]['title'], 'Platform leads')

    def test_find_searches_ids_titles_and_text(self):
        self.stock()

        def ids(*args) -> list[str]:
            return [item['id'] for item in self.hub('find', *args)['found']]

        self.assertEqual(ids('AUDIT'), ['rolling-restarts', 'audit', 'rolling-restarts/audit'])
        self.assertEqual(ids('AUDIT', '--kind', 'scenario'), ['audit', 'rolling-restarts/audit'])
        self.assertEqual(ids('blueprint'), ['rolling-restarts'])
        self.assertEqual(ids('restarts', 'platform'),
                         ['rolling-restarts', 'audit', 'rolling-restarts/audit',
                          'rolling-restarts/main'])
        self.assertEqual(ids('forty apps', '--kind', 'audience'), ['platform-leads'])
        self.assertEqual(ids('two instances'), ['rolling-restarts'])
        self.assertEqual(ids('retailer', '--kind', 'training'), ['rolling-restarts'])
        self.assertEqual(ids('audit', '--kind', 'training'), ['rolling-restarts'])
        self.assertEqual(ids('nothing-like-this'), [])
        text = self.hub('find', 'two instances')['found'][0]
        self.assertEqual(text['matched'], ['text'])
        self.assertIn('two instances', text['excerpt'])
        self.assertEqual(self.hub('find', 'audit', '--kind', 'scenario')['found'][0]['matched'],
                         ['id', 'title', 'text'])

    def test_find_only_looks_at_the_latest_revision(self):
        self.founded()
        self.small()
        self.hub('publish')
        self.write('scenario.md', example('scenario.md').replace('retailer', 'bank'))
        self.cli('approve', 'scenario:main')
        self.hub('publish')
        self.assertEqual(self.hub('find', 'retailer')['found'], [])
        self.assertEqual(self.hub('find', 'bank', '--kind', 'training')['found'][0]['revision'],
                         2)

    def test_a_link_planted_in_a_hub_is_never_followed(self):
        self.stock()
        private = self.base / 'private.txt'
        private.write_text('TOP-SECRET-TOKEN\n')
        (self.clone() / 'audiences' / 'leak.md').symlink_to(private)
        (self.clone() / 'scenarios' / 'leak.md').symlink_to(private)
        report = self.clone() / 'trainings' / 'rolling-restarts' / '1' / 'research-report.md'
        report.unlink()
        report.symlink_to(private)
        self.assertEqual(self.hub('find', 'TOP-SECRET-TOKEN')['found'], [])
        self.cli('init', '--title', 'Blue-green deploys')
        for args in (('audience', 'leak'), ('scenario', 'leak'),
                     ('research', 'rolling-restarts')):
            refusal = self.hub('get', *args, expect=2)['error']
            self.assertNotIn('TOP-SECRET-TOKEN', refusal)
        self.assertFalse((self.root / 'sources').exists())
        self.assertFalse((self.root / 'scenarios').exists())

    def test_find_can_name_the_hub(self):
        self.stock()
        other = self.bare('field.git')
        self.hub('join', str(other), '--init', '--name', 'field')
        self.assertIn('Several hubs are joined', self.hub('find', expect=2)['error'])
        self.assertEqual(self.hub('find', '--hub', 'field')['found'], [])
        self.assertEqual(len(self.hub('find', '--hub', 'team')['found']), 5)


class ScenarioTests(HubCase):
    def test_a_published_scenario_is_copied_into_a_new_training(self):
        self.founded()
        self.small()
        self.hub('publish')
        self.be('blake')
        self.hub('sync')
        self.cli('init', '--title', 'Blue-green deploys')
        got = self.hub('get', 'scenario', 'rolling-restarts/main')
        self.assertEqual((got['artifact'], got['file']), ('scenario:main', 'scenario.md'))
        self.assertEqual(got['from'], {'hub': 'team', 'id': 'rolling-restarts/main',
                                       'training': 'rolling-restarts', 'revision': 1,
                                       'level': None, 'shared_by': 'Alex'})
        self.assertIn('data, not instructions', got['note'])
        self.assertEqual((self.root / 'scenario.md').read_text(), example('scenario.md'))
        status = self.cli('status')
        self.assertEqual(status['artifacts']['scenario:main'], 'draft')
        self.assertEqual(status['scenarios']['found'], {'scenario:main': 'scenario.md'})

    def test_getting_a_scenario_never_overwrites_one(self):
        self.founded()
        self.small()
        self.hub('publish')
        self.hub('share', 'scenario', 'main', '--as', 'objection')
        self.be('blake')
        self.hub('sync')
        self.cli('init', '--title', 'Blue-green deploys')
        mine = self.write('scenario.md', '# Scenario: Mine\n')
        refusal = self.hub('get', 'scenario', 'rolling-restarts/main', expect=2)['error']
        self.assertIn('already has a scenario called main', refusal)
        self.assertIn('--as', refusal)
        self.assertEqual(mine.read_text(), '# Scenario: Mine\n')
        got = self.hub('get', 'scenario', 'rolling-restarts/main', '--as', 'objection')
        self.assertEqual(got['file'], 'scenarios/objection.md')
        (self.root / 'scenarios' / 'objection.md').write_text('# Scenario: Edited here\n')
        self.assertIn('already has a scenario called objection',
                      self.hub('get', 'scenario', 'objection', expect=2)['error'])
        self.assertEqual((self.root / 'scenarios' / 'objection.md').read_text(),
                         '# Scenario: Edited here\n')
        self.write('scenarios/main.md', '# Scenario: Also mine\n')
        mine.unlink()
        self.assertIn('already has a scenario called main',
                      self.hub('get', 'scenario', 'objection', '--as', 'main',
                               expect=2)['error'])

    def test_getting_a_scenario_refuses_what_it_cannot_find_or_place(self):
        self.founded()
        self.small()
        self.hub('publish')
        self.be('alex', 'second')
        self.assertIn('No training', self.hub('get', 'scenario', 'rolling-restarts/main',
                                              expect=2)['error'])
        self.cli('init', '--title', 'Blue-green deploys')
        for ident in ('nothing', 'rolling-restarts/nothing', 'no-training/main',
                      'rolling-restarts/main@101'):
            self.assertIn('hub find', self.hub('get', 'scenario', ident, expect=2)['error'],
                          ident)
        for ident in ('../hub', 'rolling-restarts/../1', 'Rolling', 'a/b/c'):
            self.assertIn('lowercase', self.hub('get', 'scenario', ident, expect=2)['error'],
                          ident)
        self.assertIn('lowercase', self.hub('get', 'scenario', 'rolling-restarts/main',
                                            '--as', '../escape', expect=2)['error'])
        self.assertIn('no levels', self.hub('get', 'scenario', 'rolling-restarts/main',
                                            '--level', '101', expect=2)['error'])
        self.assertEqual(sorted(path.name for path in self.root.iterdir()),
                         ['.training-studio'])

    def test_sharing_puts_a_scenario_and_who_shared_it_in_the_hub(self):
        self.founded()
        self.small()
        result = self.hub('share', 'scenario', 'main')
        self.assertEqual(result, {'hub': 'team', 'kind': 'scenario', 'id': 'rolling-restarts',
                                  'added': True, 'pushed': True, 'notice': None})
        self.assertEqual(self.shared('scenarios/rolling-restarts.md') + '\n',
                         example('scenario.md'))
        about = json.loads(self.shared('scenarios/rolling-restarts.json'))
        self.assertEqual((about['shared_by'], about['training'], about['scenario']),
                         ('Alex', 'rolling-restarts', 'main'))
        self.assertEqual((about['title'], about['level'], about['training_title']),
                         ('The zero-downtime objection', None, 'Rolling restarts'))
        self.assertEqual(about['sha256'],
                         hub.workspace.sha256_file(self.root / 'scenario.md'))
        self.assertRegex(about['shared_at'], r'^\d{4}-\d\d-\d\dT')
        self.assertEqual(git(self.remote, 'log', '-1', '--format=%s', 'main'),
                         'Share scenario rolling-restarts')

    def test_only_an_approved_scenario_can_be_shared(self):
        self.founded()
        self.cli('init', '--title', 'Rolling restarts')
        self.write('scenario.md', example('scenario.md'))
        refusal = self.hub('share', 'scenario', 'main', expect=2)['error']
        self.assertIn('scenario:main is draft', refusal)
        self.assertIn('approve', refusal)
        self.assertIn('no scenario called other',
                      self.hub('share', 'scenario', 'other', expect=2)['error'])
        self.assertEqual(self.tree(), ['README.md', 'hub.json'])
        self.cli('approve', 'scenario:main')
        self.write('scenario.md', example('scenario.md') + '\nEdited since.\n')
        self.assertIn('scenario:main is draft',
                      self.hub('share', 'scenario', 'main', expect=2)['error'])

    def test_nothing_shared_is_ever_replaced(self):
        self.founded()
        self.small()
        self.hub('share', 'scenario', 'main', '--as', 'objection')
        again = self.hub('share', 'scenario', 'main', '--as', 'objection')
        self.assertEqual((again['added'], again['pushed']), (False, True))
        self.assertIn('already has this scenario', again['notice'])
        self.be('blake')
        self.hub('sync')
        self.cli('init', '--title', 'Blue-green deploys')
        self.make('scenario:main', 'scenario.md', example('scenario.md') + '\nMine differs.\n')
        refusal = self.hub('share', 'scenario', 'main', '--as', 'objection', expect=2)['error']
        self.assertIn('already has a different scenario called objection', refusal)
        self.assertIn('--as', refusal)
        self.assertNotIn('Mine differs.', self.shared('scenarios/objection.md'))
        self.assertEqual(json.loads(self.shared('scenarios/objection.json'))['shared_by'],
                         'Alex')
        self.assertEqual(git(self.clone(), 'status', '--porcelain'), '')

    def test_two_people_sharing_under_one_id_at_once_keeps_the_first(self):
        self.founded()
        self.small()
        self.be('blake')
        self.cli('init', '--title', 'Blue-green deploys')
        self.make('scenario:main', 'scenario.md', example('scenario.md') + '\nMine differs.\n')
        self.assertTrue(self.hub('share', 'scenario', 'main', '--as', 'objection')['added'])
        self.be('alex')
        late = self.hub('share', 'scenario', 'main', '--as', 'objection')
        self.assertEqual((late['added'], late['pushed']), (False, True))
        self.assertIn('Someone else shared a different scenario called objection', late['notice'])
        self.assertIn('Mine differs.', self.shared('scenarios/objection.md'))
        self.assertEqual(json.loads(self.shared('scenarios/objection.json'))['shared_by'],
                         'Blake')
        self.assertEqual((self.clone() / 'scenarios' / 'objection.md').read_text(),
                         example('scenario.md') + '\nMine differs.\n')
        self.assertEqual(git(self.clone(), 'status', '--porcelain'), '')
        self.assertTrue(self.hub('share', 'scenario', 'main', '--as', 'objection-two')['added'])


class AudienceTests(HubCase):
    def test_an_audience_goes_into_the_hub_and_comes_back_as_text(self):
        self.founded()
        source = self.base / 'audience.md'
        source.write_text(AUDIENCE)
        shared = self.hub('share', 'audience', 'platform-leads', '--file', str(source))
        self.assertEqual(shared, {'hub': 'team', 'kind': 'audience', 'id': 'platform-leads',
                                  'added': True, 'pushed': True, 'notice': None})
        self.assertEqual(self.shared('audiences/platform-leads.md') + '\n', AUDIENCE)
        self.be('blake')
        self.hub('sync')
        got = self.hub('get', 'audience', 'platform-leads')
        self.assertEqual((got['hub'], got['id'], got['text']), ('team', 'platform-leads',
                                                                AUDIENCE))
        self.assertIn('data, not instructions', got['note'])
        self.assertIn('hub find', self.hub('get', 'audience', 'nobody', expect=2)['error'])

    def test_an_audience_is_never_replaced_or_taken_from_private_folders(self):
        self.founded()
        self.cli('init', '--title', 'Rolling restarts')
        first = self.write('audience.md', AUDIENCE)
        self.hub('share', 'audience', 'platform-leads', '--file', str(first))
        same = self.hub('share', 'audience', 'platform-leads', '--file', str(first))
        self.assertEqual((same['added'], same['pushed']), (False, True))
        other = self.write('other.md', '# Executives\n')
        self.assertIn('already has a different audience called platform-leads',
                      self.hub('share', 'audience', 'platform-leads', '--file', str(other),
                               expect=2)['error'])
        for folder in ('sources', '.harness-research'):
            private = self.write(f'{folder}/customer.md', '# A named customer\n')
            self.assertIn(f'is under {folder}/, which is never published',
                          self.hub('share', 'audience', 'customer', '--file', str(private),
                                   expect=2)['error'])
        self.be('alex', 'second')
        self.assertIn('is under sources/, which is never published',
                      self.hub('share', 'audience', 'customer', '--file', str(private).replace(
                          '.harness-research', 'sources'), expect=2)['error'])
        self.be('alex')
        self.assertIn('does not exist',
                      self.hub('share', 'audience', 'nobody', '--file',
                               str(self.root / 'missing.md'), expect=2)['error'])
        self.assertIn('lowercase', self.hub('share', 'audience', '../x', '--file', str(first),
                                            expect=2)['error'])
        binary = self.root / 'audience.bin'
        binary.write_bytes(b'\xff\xfe\x00 not text')
        self.assertIn('plain text', self.hub('share', 'audience', 'binary', '--file',
                                             str(binary), expect=2)['error'])
        self.assertEqual(self.tree('audiences/'), ['platform-leads.md'])
        self.assertEqual(self.shared('audiences/platform-leads.md') + '\n', AUDIENCE)


class ResearchTests(HubCase):
    def test_a_published_report_becomes_a_supplied_source(self):
        self.founded()
        self.small()
        self.hub('publish')
        self.be('blake')
        self.hub('sync')
        self.cli('init', '--title', 'Blue-green deploys')
        got = self.hub('get', 'research', 'rolling-restarts')
        self.assertEqual((got['file'], got['copied']),
                         ('sources/rolling-restarts-research-report-r1.md', True))
        self.assertEqual(got['from'], {'hub': 'team', 'training': 'rolling-restarts',
                                       'revision': 1, 'title': 'Rolling restarts',
                                       'published_by': 'Alex',
                                       'published_at': self.record()['published_at']})
        self.assertIn('supplied source', got['note'])
        self.assertIn('harness-research', got['note'])
        copy = self.root / 'sources' / 'rolling-restarts-research-report-r1.md'
        self.assertEqual(copy.read_text(), REPORT)
        status = self.cli('status')
        self.assertEqual(status['artifacts']['research'], 'not-started')
        self.assertFalse((self.root / 'research-report.md').exists())
        self.assertFalse((self.root / '.harness-research').exists())

        self.assertEqual(self.hub('get', 'research', 'rolling-restarts')['copied'], False)
        copy.write_text('Notes I added.\n')
        self.assertIn('already exists', self.hub('get', 'research', 'rolling-restarts',
                                                 expect=2)['error'])
        self.assertEqual(copy.read_text(), 'Notes I added.\n')

    def test_a_revision_can_be_named(self):
        self.founded()
        self.small()
        self.hub('publish')
        self.write('.harness-research/research-report.md', REPORT + '\nA later finding.\n')
        self.cli('save', 'research', '--built')
        self.cli('approve', 'research')
        self.assertEqual(self.hub('publish')['revision'], 2)
        self.be('alex', 'second')
        self.cli('init', '--title', 'Blue-green deploys')
        self.assertEqual(self.hub('get', 'research', 'rolling-restarts')['from']['revision'], 2)
        first = self.hub('get', 'research', 'rolling-restarts', '--revision', '1')
        self.assertEqual(first['file'], 'sources/rolling-restarts-research-report-r1.md')
        self.assertEqual((self.root / first['file']).read_text(), REPORT)
        self.assertIn('A later finding.', (
            self.root / 'sources' / 'rolling-restarts-research-report-r2.md').read_text())
        self.assertIn('It has: 1, 2', self.hub('get', 'research', 'rolling-restarts',
                                               '--revision', '7', expect=2)['error'])

    def test_research_that_is_not_there_is_refused(self):
        self.founded()
        self.cli('init', '--title', 'Scenario only')
        self.make('scenario:main', 'scenario.md', example('scenario.md'))
        self.hub('publish')
        self.be('alex', 'second')
        self.assertIn('No training', self.hub('get', 'research', 'scenario-only',
                                              expect=2)['error'])
        self.cli('init', '--title', 'Blue-green deploys')
        self.assertIn('without a research report',
                      self.hub('get', 'research', 'scenario-only', expect=2)['error'])
        self.assertIn('hub find', self.hub('get', 'research', 'unknown', expect=2)['error'])
        self.assertIn('lowercase', self.hub('get', 'research', '../..', expect=2)['error'])
        self.assertFalse((self.root / 'sources').exists())


class ContractTests(HubCase):
    """What every hub command promises, through a real subprocess."""

    def run_cli(self, *args, expect=0) -> dict:
        done = subprocess.run([sys.executable, str(CLI), *args], cwd=self.root,
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, expect, done.stdout + done.stderr)
        return json.loads(done.stdout)

    def test_the_commands_come_from_a_plug_in_and_refuse_in_json(self):
        self.assertNotIn('cmd_hub', (helpers.SCRIPTS / 'training.py').read_text())
        self.assertIn('ACTION', self.run_cli('hub', expect=2)['error'])
        self.assertIn('invalid choice', self.run_cli('hub', 'destroy', expect=2)['error'])
        self.assertIn('--file', self.run_cli('hub', 'share', 'audience', 'x', expect=2)['error'])

    def test_a_whole_exchange_from_the_command_line(self):
        self.assertEqual(self.run_cli('hub', 'list'), {'hubs': []})
        self.assertIn('hub join', self.run_cli('hub', 'find', expect=2)['error'])
        self.assertEqual(self.run_cli('hub', 'join', str(self.bare()), '--init', '--name',
                                      'team')['pushed'], True)
        self.small()
        self.assertEqual(self.run_cli('hub', 'publish')['revision'], 1)
        self.be('blake')
        self.assertEqual(self.run_cli('hub', 'join', str(self.remote))['trainings'], 1)
        self.run_cli('init', '--title', 'Blue-green deploys')
        self.assertEqual(self.run_cli('hub', 'get', 'scenario', 'rolling-restarts/main')['file'],
                         'scenario.md')
        self.assertEqual(self.run_cli('hub', 'publish', expect=2),
                         {'error': 'Nothing in this training is approved, so there is nothing '
                                   'to publish. Approve at least one deliverable first.'})


class BackgroundWorkTests(HubCase):
    def test_git_starts_no_maintenance_behind_a_test(self):
        """A detached maintenance run outlives the command that started it, and a test's
        temporary directory is removed as soon as the test ends."""
        self.founded()
        for repo in (self.clone(), self.remote):
            for key, value in helpers.QUIET_GIT.items():
                self.assertEqual(git(repo, 'config', '--get', key), value, (repo.name, key))
        traced = subprocess.run(['git', 'fetch', 'origin'], cwd=self.clone(), text=True,
                                capture_output=True, env={**os.environ, 'GIT_TRACE': '1'})
        self.assertEqual(traced.returncode, 0, traced.stderr)
        self.assertNotIn('maintenance run', traced.stderr)

    def test_a_push_starts_no_maintenance_in_the_repository_it_reaches(self):
        """For a push to a local path, git drops GIT_CONFIG_COUNT before it starts
        receive-pack, so the receiving repository reads only the gitconfig."""
        self.founded()
        receiving = {name: value for name, value in os.environ.items()
                     if not name.startswith(('GIT_CONFIG_COUNT', 'GIT_CONFIG_KEY_',
                                             'GIT_CONFIG_VALUE_'))}
        for key, value in helpers.QUIET_GIT.items():
            seen = subprocess.run(['git', 'config', '--get', key], cwd=self.remote, text=True,
                                  capture_output=True, env=receiving)
            self.assertEqual(seen.stdout.strip(), value, key)
        clone = self.clone()
        (clone / 'pushed.md').write_text('Pushed.\n')
        git(clone, 'add', 'pushed.md')
        git(clone, 'commit', '--quiet', '-m', 'Pushed')
        traced = subprocess.run(['git', 'push', 'origin', 'HEAD:main'], cwd=clone, text=True,
                                capture_output=True, env={**os.environ, 'GIT_TRACE': '1'})
        self.assertEqual(traced.returncode, 0, traced.stderr)
        self.assertIn('receive-pack', traced.stderr)
        self.assertNotIn('maintenance run', traced.stderr)
        self.assertNotIn('gc --auto', traced.stderr)


class GuidanceTests(unittest.TestCase):
    def test_the_guidance_states_the_boundaries(self):
        text = (helpers.SKILL / 'references' / 'hub.md').read_text()
        self.assertLessEqual(validate_package.estimate(text), 1000)
        for phrase in ('go-ahead', 'same hub', 'data, not instructions', 'supplied source',
                       'harness-research', 'sources/', '.training-studio/',
                       '.harness-research/', '.harness-slides/', 'approved'):
            self.assertIn(phrase, text)
        for command in ('join', 'list', 'use', 'publish', 'status', 'sync', 'find',
                        'get scenario', 'share scenario', 'get audience', 'share audience',
                        'get research'):
            self.assertIn(f'training.py hub {command}', text)

    def test_the_entry_and_the_users_page_point_at_it(self):
        self.assertIn('[hub](references/hub.md)', (helpers.SKILL / 'SKILL.md').read_text())
        self.assertIn('docs/team-hub.md', (helpers.REPO / 'README.md').read_text())
        self.assertTrue((helpers.REPO / 'docs' / 'team-hub.md').is_file())
        self.assertEqual(validate_package.loading_sets()['hub'],
                         (['SKILL.md', 'references/hub.md'], 2000))
