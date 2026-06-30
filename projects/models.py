from collections import defaultdict
from datetime import datetime

import django.db
from django.db import models

from users.models import User


class ProjectManager(models.Manager):
    def makeNewOwner(self, project):
        """

        :param project:
        :return:
        """
        if User.objects.get(project.owner_id) is not None:
            raise ValueError("The owner didnt delete his account")

    def create_project(self, user, name, description):
        """
        Creates a project and automatically sets the given user as owner
        :param user: The future project creator and owner
        :return:
        """
        proj = self.create(owner_id=user, name=name, description=description)
        default_roles = ProjectRole.objects.create_default_project_roles(proj)
        UserProjectRole.objects.give_role(proj.owner, proj, default_roles[0][0].id)

    def delete_project(self, project):
        """
        Deletes a project from the database
        :param project:
        :return:
        """
        Project.objects.get(id=project.id).delete()
        return Project.objects.filter(id=project.id).count() == 0

    def get_user_projects(self, user):
        """
        Returns all the projects that an specified user participated in
        :param project:
        :return:
        """
        #return self.filter(id__in=UserProjectRole.objects.filter(user_id=user.id)).values_list('id',flat=True)


class Project(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100, blank=False, null=False, default='New project')
    description = models.CharField(max_length=5000, blank=False, null=False, default='Project description')
    root_link = models.CharField(max_length=1000,blank=False,null=False,default='root_github')
    objects = ProjectManager()

    class Meta:
        db_table = 'projects'


class ProjectDomainManager(models.Manager):
    def add_domains_to_project(self, project, domain_names):
        """
        :param project:
        :param domain_names:
        :return:
        """
        domains = [ProjectDomain(project=project, domain=name) for name in domain_names]
        succes = self.bulk_create(domains)
        return succes

    def remove_domains_from_project(self, project, domain_names):
        """

        :param project:
        :param domain_names:
        :return:
        """
        try:
            domains = self.filter(project=project, domain__in=domain_names).delete()
            return domains
        except django.db.DatabaseError as e:
            print(str(e))

    def get_project_domains(self, project):
        return self.filter(project_id=project.id).values('domain')


class ProjectDomain(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    domain = models.CharField(max_length=100, blank=False, null=False, default='new domain')
    objects = ProjectDomainManager()

    class Meta:
        db_table = 'project_domains'


class ProjectTaskManager(models.Manager):
    def get_project_tasks(self, project):
        try:
            taskuri = self.select_related('project').filter(project=project)
            return taskuri
        except django.db.DatabaseError as e:
            print(str(e))
            return []

    def add_task_to_project(self, project, name, description, start_date, end_date):
        try:
            _start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
            _end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
            var = self.filter(project=project,name=name)
            print(var.count())
            if self.filter(project=project,name=name).count() > 0:
                return
            if _start_date > _end_date:
                return
            if len(description) > 300:
                return
            return self.create(project_id=project.id,
                               name=name,
                               description=description,
                               start_date=start_date,
                               end_date=end_date,
                               finished=False
                               )
        except django.db.DatabaseError as e:
            print(str(e))
            return []

    def remove_tasks_from_project(self,tasks):
        try:
            searched = self.filter(name__in=tasks)
            return searched.delete()
        except django.db.DatabaseError as e:
            print(str(e))
            return []

class ProjectTask(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    name = models.CharField(max_length=100, default='New task', blank=True)
    description = models.CharField(max_length=300, default='Describe the task..', blank=True)
    start_date = models.DateField(default='1000-10-10')
    end_date = models.DateField(default='3000-10-10')
    finished = models.BooleanField(default=False)
    objects = ProjectTaskManager()

    class Meta:
        db_table = 'projects_tasks'
        ordering = ['end_date']
        indexes = [
            models.Index(fields=['end_date'], name='end_date_idx'),
        ]


class UserRoleValidator():
    def is_operation_permitted(self, project, role_assignator, user, new_role):
        """

        :param role_assignator:
        :param user:
        :param new_role:
        :return:
        """
        _project = Project.objects.get(id=project)
        if _project is None:
            raise ValueError("Project not found")
        _role_assigner = User.objects.get(id=role_assignator)
        if user is None:
            raise ValueError("Role assignator not found")
        _user = User.objects.get(id=user)
        if _user is None:
            raise ValueError("User not found")
        if _project.owner_id == role_assignator:
            return True
        #is_assigner = UserRoleManager.is_user_in_project(_project,_role_assigner)
        #is_user = UserRoleManager.is_user_in_project(_project, _user)
        #if not is_assigner:
        #    raise ValueError("Assigner not found")
        #if not is_user:
        #    raise ValueError("User not found")
        #permission checking TODO
        return True


class ProjectRoleManager(models.Manager):
    def create_default_project_roles(self, project):
        try:
            from devnetwork.settings import DEFAULT_PROJECT_ROLES
            created_roles = []
            for role_name, role_permissions in DEFAULT_PROJECT_ROLES.items():
                role = ProjectRole.objects.get_or_create(
                    name=role_name,
                    defaults=role_permissions
                )
                created_roles.append(role)
            return created_roles
        except django.db.Error as e:
            print(str(e))

    def modify_project_role(self, project, form):
        try:
            print('todo')
        except django.db.Error as e:
            print(str(e))
        except Exception as ex:
            print(str(ex))
    def get_project_roles(self,project):
        try:
            return self.filter(role__project=project).distinct()
        except django.db.Error as e:
            print(str(e))
            return []


class ProjectRole(models.Model):
    name = models.CharField(max_length=50, default='new role', null=False, blank=True)
    can_accept_invites = models.BooleanField(default=False)
    can_invite_others = models.BooleanField(default=False)
    can_kick_others = models.BooleanField(default=False)
    can_change_roles = models.BooleanField(default=False)
    can_start_calls = models.BooleanField(default=False)
    can_add_tasks = models.BooleanField(default=False)
    can_delete_tasks = models.BooleanField(default=False)
    can_modify_tasks = models.BooleanField(default=False)
    can_modify_files = models.BooleanField(default=False)
    can_execute_code = models.BooleanField(default=False)
    can_share_file_access = models.BooleanField(default=False)
    can_change_project_settings = models.BooleanField(default=False)
    objects = ProjectRoleManager()

    class Meta:
        db_table = 'project_roles'


class UserProjectRoleManager(models.Manager):
    def make_new_owner(self, project):
        """

        :param project:
        :return:
        """

    def give_role(self, user, project, role):
        role = self.model(user_id=user.id, project_id=project.id, role_id=role)
        role.save()

    def get_user_role_in_project(self, project, user):
        """
        Gets an user's role in a project if it exists,else labels them as visitors
        :param project:
        :param user:
        :return:
        """
        try:
            role_obj = self.get_queryset().filter(
                project=project,
                user=user
            ).select_related('role').first()
            return role_obj.role.name if role_obj else 'visitor'
        except UserProjectRole.DoesNotExist:
            return 'visitor'

    def get_role_permissions(self, role_name, project):
        try:
            user_project_role = self.get_queryset().filter(
                project=project,
                role__name=role_name,
            ).select_related('role').first()

            permission_keys = [
                'can_accept_invites', 'can_invite_others', 'can_kick_others',
                'can_change_roles', 'can_start_calls', 'can_add_tasks',
                'can_delete_tasks', 'can_modify_tasks', 'can_modify_files',
                'can_execute_code', 'can_share_file_access', 'can_change_project_settings'
            ]
            if not user_project_role:
                return {k: False for k in permission_keys}
            role = user_project_role.role
            return {k: getattr(role, k) for k in permission_keys}
        except Exception as e:
            print(str(e))
            return {k: False for k in [
                'can_accept_invites', 'can_invite_others', 'can_kick_others',
                'can_change_roles', 'can_start_calls', 'can_add_tasks',
                'can_delete_tasks', 'can_modify_tasks', 'can_modify_files',
                'can_execute_code', 'can_share_file_access', 'can_change_project_settings'
            ]}

    def give_role_to_user(self, project: int, role_assigner: int, user: int, role):
        """

        :param project:
        :param role_assigner:
        :param user:
        :param role:
        :return:
        """
        try:
            if not UserRoleValidator.is_operation_permitted(project, role_assigner, user, role):
                return False
            role = self.get(project_id=project, user_id=user)
            if role is None:
                return self.create(project_id=project, user_id=user, role=role)
            role.update(role=role)
        except ValueError:
            return False
        except django.db.DatabaseError as e:
            return False

    def get_all_users_in_project(self, project):
        """
        Returns the whole users that ever participated/are participating now in a project
        :param project:
        :return: A dictionary with the participants grouped by the roles in the given project
        """
        users_by_role = defaultdict(list)
        roles = self.get_queryset().filter(project=project).select_related('user', 'role')
        for role_obj in roles:
            users_by_role[role_obj.role.name].append(role_obj.user)
        return dict(users_by_role)

    def find_valid_admins(self, project, requested_access):
        """
        Finds the admins that can respond to a file request access in a project
        :param project: the project itself
        :param requested_access: A list of the urls of the requested files for access
        :return: a list of all the admins
        """
        try:
            id_role_owner, id_role_project_manager, id_role_admin = 1, 2, 3
            can_always_respond = [role.user for role in self.filter(
                                        role_id__in=[id_role_owner,id_role_project_manager,id_role_admin],
                                        project_id=project.id
                                        ).select_related('user').distinct()]

            can_also_provide_access = [participation.user for participation in
                                        ProjectTaskParticipation.objects.filter(
                                            task__project_id=project.id,
                                            task__resource_accesses__resource_path__in=requested_access,
                                       ).select_related('user').distinct()
                                      ]
            return can_always_respond + can_also_provide_access
        except django.db.DatabaseError as e:
            print(str(e))
            return None


class UserProjectRole(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, default=-1,related_name='user')
    project = models.ForeignKey(Project, on_delete=models.CASCADE, default=-1,related_name='project')
    role = models.ForeignKey(ProjectRole, on_delete=models.CASCADE, default=-1,related_name='role')
    objects = UserProjectRoleManager()

    class Meta:
        db_table = 'user_project_roles'


class ProjectTaskParticipationManager(models.Manager):
    def add_task_participations(self, task, users):
        try:
            participations = [ProjectTaskParticipation(user=user, task=task) for user in users]
            self.bulk_create(participations)
        except django.db.DatabaseError:
            return

    def remove_task_participations(self, task, users):
        try:
            participations = [self.filter(task=task, user=user) for user in users]
            for p in participations:
                p.delete()
        except django.db.DatabaseError:
            return


class ProjectTaskParticipation(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    task = models.ForeignKey(ProjectTask, on_delete=models.CASCADE, null=True, blank=True)
    objects = ProjectTaskParticipationManager()

    class Meta:
        db_table = 'project_task_participations'
        managed = False

class ProjectRequiementSectionManager(models.Manager):
    def add_requirement_sections(self, project, names):
        """

        :param project:
        :param names:
        :return:
        """
        try:
            new_sections = [ProjectRequirementSection(project=project, name=skill_name) for skill_name in names]
            created = self.bulk_create(new_sections, batch_size=100)
            if len(created) != len(names):
                raise ValueError("All sections couldn't be added")
            return created
        except django.db.DatabaseError as e:
            print(str(e))

    def remove_requirement_sections(self, project, names):
        """

        :param project:
        :param names:
        :return:
        """
        try:
            former_sections = self.filter(project=project, name__in=names).delete()
            return former_sections
        except django.db.DatabaseError as e:
            print(str(e))

    def change_requirement_sections_titles(self, project, old_names, new_names):
        """

        :param project:
        :param old_names:
        :param new_names:
        :return:
        """
        try:
            former_sections = self.select_for_update(project=project, name__in=old_names)
            for section in former_sections:
                pass
            return former_sections
        except django.db.DatabaseError as e:
            print(str(e))


class ProjectRequirementSection(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    name = models.CharField(max_length=50, null=False, blank=False,
                            default='Choose a new skill section(Frontend/Backend/Database etc..)')
    objects = ProjectRequiementSectionManager()

    class Meta:
        db_table = 'project_requirements_sections'


class ProjectSkillRequirementManager(models.Manager):
    def add_skill_requirements(self, section, names):
        try:
            new_requirements = [ProjectSkillRequirement(section=section, name=skill_name) for skill_name in names]
            created = self.bulk_create(new_requirements, batch_size=100)
            if len(created) != len(names):
                raise ValueError("All sections couldn't be added")
            return created
        except django.db.DatabaseError as e:
            print(str(e))

    def remove_skill_requirements(self, section, names):
        """

        :param section:
        :param names:
        :return:
        """
        try:
            reqs = self.filter(section=section, name__in=names).select_for_update()
            former_requirements = reqs.delete()
            return former_requirements
        except django.db.DatabaseError as e:
            print(str(e))

    def get_requirements_grouped_by_sections(self, project):
        """

        :param project:
        :return:
        """
        try:
            result = {}
            sections = ProjectRequirementSection.objects.filter(project=project)
            requirements = ProjectSkillRequirement.objects.filter(section__in=sections).select_related('section')
            for sec in sections:
                result[sec.name] = []
            for req in requirements:
                result[req.section.name].append({
                    'id': req.id,
                    'skill': req.name
                })
            return result
        except django.db.DatabaseError as e:
            print(str(e))


class ProjectSkillRequirement(models.Model):
    section = models.ForeignKey(ProjectRequirementSection, on_delete=models.CASCADE)
    name = models.CharField(max_length=50, null=False, blank=False,
                            default='Choose a new required skill (Java/Aws/ChatGPT ...)')
    objects = ProjectSkillRequirementManager()

    class Meta:
        db_table = 'project_skill_requirements'


class ResourceAccess(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    resource_path = models.CharField(max_length=255)
    allowed_users = models.ManyToManyField(User, related_name='accessible_resources')
    managers = models.ManyToManyField(User, related_name='managed_resources', blank=True)
    locked_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,related_name='locked_resources')
    locked_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        unique_together = ('project', 'resource_path')


class TaskResourceAccessManager(models.Manager):
    def add_resources_to_task(self, task, resource_paths):
        """
        Affiliates the given file/folder paths with a task, granting access
        to every user participating in that task.
        """
        entries = [self.model(task=task, resource_path=path) for path in resource_paths]
        try:
            return self.bulk_create(entries, ignore_conflicts=True)
        except django.db.DatabaseError as e:
            print(str(e))
            return []

    def remove_resources_from_task(self, task, resource_paths):
        try:
            return self.filter(task=task, resource_path__in=resource_paths).delete()
        except django.db.DatabaseError as e:
            print(str(e))

    def user_has_access_to_path(self, user, project, file_path):
        """
        ReBAC check: a user can touch a path if they participate in a task
        that the path (or one of its parent folders) was affiliated with.
        """
        task_ids = ProjectTaskParticipation.objects.filter(
            user=user, task__project=project
        ).values_list('task_id', flat=True)
        if not task_ids:
            return False
        resources = self.filter(task_id__in=task_ids)
        for resource in resources:
            resource_path = resource.resource_path.rstrip('/')
            if file_path == resource_path or file_path.startswith(resource_path + '/'):
                return True
        return False


class TaskResourceAccess(models.Model):
    task = models.ForeignKey(ProjectTask, on_delete=models.CASCADE, related_name='resource_accesses')
    resource_path = models.CharField(max_length=255)
    objects = TaskResourceAccessManager()

    class Meta:
        db_table = 'task_resource_accesses'
        unique_together = ('task', 'resource_path')