import json
import secrets
from datetime import date

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from projects.models import (
    Project, ProjectRepoStats, ProjectRequirementSection, ProjectSkillRequirement, UserProjectRole,
)
from users.models import User


class ProjectCreationTests(TestCase):
    def setUp(self):
        # ratelimit counters live outside the DB transaction rollback (Redis),
        # so clear them for a clean slate on every test - same reasoning as
        # users.tests.UsersTests.setUp.
        cache.clear()
        suffix = secrets.token_hex(4)
        # NOTE: prefix picked deliberately - 'projectcreator_' shares enough
        # characters with 'CorrectHorseBatteryStaple123' that difflib's
        # quick_ratio() (used by UserAttributeSimilarityValidator) flags them
        # as "too similar" on ~3% of random suffixes, making create_user()
        # intermittently return None. 'projowner_' doesn't collide.
        self.user = User.objects.create_user(
            username=f'projowner_{suffix}',
            email=f'projowner_{suffix}@example.com',
            password='CorrectHorseBatteryStaple123',
            birthday=date(2000, 1, 1),
        )

    @staticmethod
    def _create_url():
        return reverse('users:create_project')

    def _post(self, payload):
        return self.client.post(self._create_url(), data=json.dumps(payload), content_type='application/json')

    # ---- happy path ----

    def test_create_project_minimal_succeeds(self):
        self.client.force_login(self.user)
        response = self._post({'name': f'proj_{secrets.token_hex(4)}', 'description': 'a project'})
        self.assertEqual(response.status_code, 201)
        data = response.json()['project']
        self.assertEqual(data['needed_skills'], {})
        self.assertEqual(data['github_repos'], [])
        self.assertTrue(Project.objects.filter(id=data['id']).exists())

    def test_create_project_makes_creator_the_owner_with_a_role(self):
        self.client.force_login(self.user)
        name = f'proj_{secrets.token_hex(4)}'
        response = self._post({'name': name, 'description': 'a project'})
        project = Project.objects.get(id=response.json()['project']['id'])
        self.assertEqual(project.owner_id, self.user.id)
        role = UserProjectRole.objects.get_user_role_in_project(project, self.user)
        self.assertNotEqual(role, 'visitor', "the creator must automatically get a real role, not fall back to visitor")

    # ---- needed_skills: dict of {domain: [skill, ...]} ----

    def test_create_project_with_needed_skills_creates_sections_and_requirements(self):
        self.client.force_login(self.user)
        name = f'proj_{secrets.token_hex(4)}'
        response = self._post({
            'name': name,
            'description': 'a project',
            'needed_skills': {'Backend': ['Python', 'SpringBoot'], 'Frontend': ['React']},
        })
        self.assertEqual(response.status_code, 201)
        project = Project.objects.get(id=response.json()['project']['id'])

        sections = {s.name for s in ProjectRequirementSection.objects.filter(project=project)}
        self.assertEqual(sections, {'Backend', 'Frontend'})

        backend_skills = set(ProjectSkillRequirement.objects.filter(
            section__project=project, section__name='Backend'
        ).values_list('name', flat=True))
        self.assertEqual(backend_skills, {'Python', 'SpringBoot'})

        response_skills = response.json()['project']['needed_skills']
        self.assertEqual(set(response_skills.keys()), {'Backend', 'Frontend'})
        self.assertEqual({s['skill'] for s in response_skills['Backend']}, {'Python', 'SpringBoot'})

    def test_create_project_rejects_needed_skills_that_are_not_a_domain_to_skill_list_mapping(self):
        self.client.force_login(self.user)
        name = f'proj_{secrets.token_hex(4)}'
        response = self._post({
            'name': name,
            'description': 'a project',
            'needed_skills': {'Backend': 'Python'},  # should be a list, not a bare string
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Project.objects.filter(name=name).exists())

    def test_create_project_rejects_needed_skills_given_as_a_list_instead_of_a_dict(self):
        self.client.force_login(self.user)
        name = f'proj_{secrets.token_hex(4)}'
        response = self._post({
            'name': name,
            'description': 'a project',
            'needed_skills': ['Backend', 'Frontend'],
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Project.objects.filter(name=name).exists())

    # ---- github_repos: list of {github_repo_name, github_repo_link, github_repo_access_token} ----

    def test_create_project_with_github_repos_creates_and_links_repo_stats(self):
        self.client.force_login(self.user)
        name = f'proj_{secrets.token_hex(4)}'
        response = self._post({
            'name': name,
            'description': 'a project',
            'github_repos': [{
                'github_repo_name': 'my-repo',
                'github_repo_link': 'https://github.com/someowner/my-repo',
                'github_repo_access_token': 'ghp_supersecrettoken',
            }],
        })
        self.assertEqual(response.status_code, 201)
        project = Project.objects.get(id=response.json()['project']['id'])

        repo_stat = project.repo_stats.get()
        self.assertEqual(repo_stat.github_repo_name, 'my-repo')
        self.assertEqual(repo_stat.github_repo_link, 'https://github.com/someowner/my-repo')
        self.assertEqual(
            repo_stat.github_token, 'ghp_supersecrettoken',
            "github_repo_access_token from the request must land in the model's github_token field"
        )

    def test_create_project_response_never_echoes_back_the_access_token(self):
        self.client.force_login(self.user)
        name = f'proj_{secrets.token_hex(4)}'
        response = self._post({
            'name': name,
            'description': 'a project',
            'github_repos': [{
                'github_repo_name': 'my-repo',
                'github_repo_link': 'https://github.com/someowner/my-repo',
                'github_repo_access_token': 'ghp_supersecrettoken',
            }],
        })
        self.assertNotIn('ghp_supersecrettoken', response.content.decode())
        repos = response.json()['project']['github_repos']
        self.assertEqual(len(repos), 1)
        self.assertNotIn('github_repo_access_token', repos[0])
        self.assertNotIn('github_token', repos[0])

    def test_create_project_github_repo_access_token_is_optional(self):
        self.client.force_login(self.user)
        name = f'proj_{secrets.token_hex(4)}'
        response = self._post({
            'name': name,
            'description': 'a project',
            'github_repos': [{
                'github_repo_name': 'public-repo',
                'github_repo_link': 'https://github.com/someowner/public-repo',
            }],
        })
        self.assertEqual(response.status_code, 201)
        project = Project.objects.get(id=response.json()['project']['id'])
        self.assertEqual(project.repo_stats.get().github_token, '')

    def test_create_project_rejects_github_repos_missing_required_keys(self):
        self.client.force_login(self.user)
        name = f'proj_{secrets.token_hex(4)}'
        response = self._post({
            'name': name,
            'description': 'a project',
            'github_repos': [{'github_repo_name': 'no-link-repo'}],  # github_repo_link missing
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Project.objects.filter(name=name).exists())
        self.assertFalse(ProjectRepoStats.objects.filter(github_repo_name='no-link-repo').exists())

    def test_create_project_rejects_github_repos_given_as_a_dict_instead_of_a_list(self):
        self.client.force_login(self.user)
        name = f'proj_{secrets.token_hex(4)}'
        response = self._post({
            'name': name,
            'description': 'a project',
            'github_repos': {
                'github_repo_name': 'my-repo',
                'github_repo_link': 'https://github.com/someowner/my-repo',
            },
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Project.objects.filter(name=name).exists())

    # ---- pre-existing validation, now on the JSON path ----

    def test_create_project_rejects_duplicate_name(self):
        self.client.force_login(self.user)
        name = f'proj_{secrets.token_hex(4)}'
        first = self._post({'name': name, 'description': 'first'})
        self.assertEqual(first.status_code, 201)

        second = self._post({'name': name, 'description': 'second'})
        self.assertEqual(second.status_code, 400)
        self.assertEqual(Project.objects.filter(name=name).count(), 1)

    def test_create_project_rejects_name_that_fails_slug_validation(self):
        self.client.force_login(self.user)
        response = self._post({'name': 'not a valid slug!!!', 'description': 'a project'})
        self.assertEqual(response.status_code, 400)

    def test_create_project_missing_name_returns_400_not_500(self):
        """
        Before the JSON migration this read request.POST['name'] directly -
        a missing field raised an unhandled KeyError (500). It must now be a
        clean 400.
        """
        self.client.force_login(self.user)
        response = self._post({'description': 'a project'})
        self.assertEqual(response.status_code, 400)

    def test_create_project_invalid_json_body_returns_400_not_500(self):
        self.client.force_login(self.user)
        response = self.client.post(self._create_url(), data='not json', content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_create_project_requires_authentication(self):
        response = self._post({'name': f'proj_{secrets.token_hex(4)}', 'description': 'a project'})
        self.assertEqual(response.status_code, 302)

    def test_create_project_get_returns_ready_status(self):
        self.client.force_login(self.user)
        response = self.client.get(self._create_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'ready')

    # ---- rate limiting ----

    def test_create_project_rate_limit_blocks_after_20_requests_per_user(self):
        """create_project rate-limits POST by 'user' at 20/m."""
        self.client.force_login(self.user)

        for attempt in range(20):
            response = self._post({'name': f'ratelimitproj_{attempt}_{secrets.token_hex(4)}', 'description': 'd'})
            self.assertEqual(
                response.status_code, 201,
                f"attempt {attempt + 1} should succeed normally, got {response.status_code}"
            )

        blocked_response = self._post({
            'name': f'ratelimitproj_blocked_{secrets.token_hex(4)}', 'description': 'd'
        })
        self.assertEqual(
            blocked_response.status_code, 403,
            "21st POST within a minute from the same user should be rate-limited (user, 20/m)"
        )
