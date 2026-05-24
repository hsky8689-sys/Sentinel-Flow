import base64
import json

import django.db
import requests
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db.models import QuerySet
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST
from django_ratelimit.decorators import ratelimit

import users.views
from devnetwork import settings
from projects.models import Project, UserProjectRole, ProjectDomain, ProjectSkillRequirement, ProjectRequirementSection, \
    ProjectTask, ProjectRole, ResourceAccess
from users.models import User, UserRequest


@login_required
def create_project(request):
    if request.method == 'POST':

        users.views.acces_profile(request,request.user.username)
    else:
        return JsonResponse({'status': 'error',
                      'code' : 404
                      })
@login_required
def open_project_page(request,name):
    project = Project.objects.filter(name=name).first()
    if not project:
        return JsonResponse({'status': 'failed', 'code': 404})
    staff = UserProjectRole.objects.get_all_users_in_project(project)
    user_role = UserProjectRole.objects.get_user_role_in_project(project, request.user)
    visitor_permissions = UserProjectRole.objects.get_role_permissions(user_role,project)
    project_domains = ProjectDomain.objects.get_project_domains(project)
    owner_username,repo_name='no_github_owner_set','no_github_name_set'
    if project.root_link:
        root_link = project.root_link.split('/')
        owner_username,repo_name = root_link[3],root_link[4]
    context_data = {
        'role': user_role,
        'user_id': request.user.id,
        'user_username': request.user.username,
        'project_name': project.name,
        'project_id': project.id,
        'owner_github_name':owner_username,
        'repo_name':repo_name,
        'repository_link' : project.root_link,
        'staff': staff,
        'roles': list(staff.keys()),
        'domains':list(project_domains),
        'description':project.description,
        'visitor_permissions':visitor_permissions
    }
    return render(request, 'html/project_page.html', {'stats': context_data})
@login_required
def open_project_members_page(request,name):
    project = Project.objects.filter(name=name).first()
    result = UserProjectRole.objects.get_all_users_in_project(project)
    stats = {'members': result, 'project_name': project.name}
    return render(request, 'html/project_members_page.html', {'stats': stats})

@login_required
@csrf_exempt
def open_project_settings(request, name):
    project = get_object_or_404(Project, name=name)
    user_role = UserProjectRole.objects.get_user_role_in_project(project, request.user)

    context_data = {
        'project_name': project.name,
        'project_id': project.id,
        'role': user_role,
        'user_username': request.user.username,
    }
    return render(request, 'html/project_settings_page.html', {'stats': context_data})
@require_http_methods(["GET"])
@csrf_exempt
def api_get_project_domains(request,name):
    try:
        project = get_object_or_404(Project,name=name)
        domains = ProjectDomain.objects.filter(project_id=project.id)
        return JsonResponse({'status':'success','domains':list(domains.values())})
    except django.db.DatabaseError:
        return JsonResponse({'status': 'error', 'code': 500})
@require_http_methods(["POST"])
@csrf_exempt
def api_add_project_domains(request,name):
    try:
        if request.method == 'POST':
            project = get_object_or_404(Project,name=name)
            role = UserProjectRole.objects.get_user_role_in_project(project,request.user)
            if UserProjectRole.objects.get_role_permissions(role,project)['can_change_project_settings']:
                data = json.loads(request.body)
                domains = data.get('newDomains',[])
                succes = ProjectDomain.objects.add_domains_to_project(project,domains)
                return JsonResponse({'status':'succes' if len(succes) == len(domains) else 'error',
                             'code':200 if len(succes) == len(domains) else 404
                })
            else:
                return JsonResponse({'status':'Unauthorized access','code':403})
    except Exception as e:
        print(str(e))
    except django.db.DatabaseError:
        return JsonResponse({'status': 'error', 'code': 500})
@require_http_methods(["POST"])
@csrf_exempt
def api_delete_project_domains(request,name):
    try:
        if request.method == 'POST':
            project = get_object_or_404(Project, name=name)
            role = UserProjectRole.objects.get_user_role_in_project(project, request.user)
            if UserProjectRole.objects.get_role_permissions(role, project)['can_change_project_settings']:
                data = json.loads(request.body)
                domains = data.get('removedDomains', [])
                succes = ProjectDomain.objects.remove_domains_from_project(project, domains)
                return JsonResponse({'status': 'succes' if len(succes) == len(domains) else 'error',
                                     'code': 200 if len(succes) == len(domains) else 404
                                     })
            else:
                return JsonResponse({'status': 'Unauthorized access', 'code': 403})
    except Exception as e:
        print(str(e))
    except django.db.DatabaseError:
        return JsonResponse({'status': 'error', 'code': 500})
@require_http_methods(["GET"])
@csrf_exempt
def api_get_project_requirements(request,name):
    try:
        project = get_object_or_404(Project,name=name)
        succes = ProjectSkillRequirement.objects.get_requirements_grouped_by_sections(project)
        return JsonResponse({'status':'succes','requirements':succes})
    except Exception as e:
        print(str(e))
    except django.db.DatabaseError:
        return JsonResponse({'status': 'error', 'code': 404})
@require_http_methods(["POST"])
@csrf_exempt
def api_add_project_requirements(request,name):
    try:
        project = get_object_or_404(Project, name=name)
        role = UserProjectRole.objects.get_user_role_in_project(project, request.user)
        if UserProjectRole.objects.get_role_permissions(role, project)['can_change_project_settings']:
            data = json.loads(request.body)
            requirements = data.get('newRequirements',[])
            manager = ProjectSkillRequirement.objects
            section_manager = ProjectRequirementSection.objects
            batches = {}
            for req in requirements:
                if batches.get(req[0]):
                    batches[req[0]].append(req[1])
                else:
                    batches[req[0]] = [req[1]]
            for key in batches.keys():
                section = section_manager.get(project=project,name=key)
                manager.add_skill_requirements(section,batches[key])
            return JsonResponse({'status':'succes'})
        else:
            return JsonResponse({'status': 'Unauthorized access', 'code': 403})
    except Exception as e:
        print(str(e))
    except django.db.DatabaseError:
        return JsonResponse({'status': 'error', 'code': 404})
@require_http_methods(["POST"])
@csrf_exempt
def api_remove_project_requirements(request,name):
    try:
        project = get_object_or_404(Project, name=name)
        role = UserProjectRole.objects.get_user_role_in_project(project, request.user)
        if UserProjectRole.objects.get_role_permissions(role, project)['can_change_project_settings']:
            data = json.loads(request.body)
            requirements = data.get('removedRequirements',[])
            manager = ProjectSkillRequirement.objects
            section_manager = ProjectRequirementSection.objects
            batches = {}
            for req in requirements:
                if batches.get(req[0]):
                    batches[req[0]].append(req[1])
                else:
                    batches[req[0]] = [req[1]]
            for key in batches.keys():
                section = section_manager.get(project=project,name=key)
                manager.remove_skill_requirements(section,batches[key])
            return JsonResponse({'status':'succes'})
        else:
            return JsonResponse({'status': 'Unauthorized access', 'code': 403})
    except Exception as e:
        print(str(e))
    except django.db.DatabaseError:
        return JsonResponse({'status': 'error', 'code': 404})
@require_http_methods(["POST"])
@csrf_exempt
def api_remove_project_sections(request,name):
    try:
        project = get_object_or_404(Project, name=name)
        role = UserProjectRole.objects.get_user_role_in_project(project, request.user)
        if UserProjectRole.objects.get_role_permissions(role, project)['can_change_project_settings']:
            data = json.loads(request.body)
            requirements = data.get('removedSections',[])
            ProjectRequirementSection.objects.remove_requirement_sections(project,requirements)
            return JsonResponse({'status':'succes'})
        else:
            return JsonResponse({'status': 'Unauthorized access', 'code': 403})
    except Exception as e:
        print(str(e))
    except django.db.DatabaseError:
        return JsonResponse({'status': 'error', 'code': 404})
@require_http_methods(["POST"])
@csrf_exempt
def api_add_project_sections(request,name):
    try:
        project = get_object_or_404(Project, name=name)
        role = UserProjectRole.objects.get_user_role_in_project(project, request.user)
        if UserProjectRole.objects.get_role_permissions(role, project)['can_change_project_settings']:
            data = json.loads(request.body)
            requirements = data.get('newSections',[])
            ProjectRequirementSection.objects.add_requirement_sections(project,requirements)
            return JsonResponse({'status':'succes'})
        else:
            return JsonResponse({'status': 'Unauthorized access', 'code': 403})
    except Exception as e:
        print(str(e))
    except django.db.DatabaseError:
        return JsonResponse({'status': 'error', 'code': 404})
@csrf_exempt
@require_http_methods(["GET"])
def api_get_project_tasks(request,name):
    try:
        project = get_object_or_404(Project, name=name)
        role = UserProjectRole.objects.get_user_role_in_project(project, request.user)
        if UserProjectRole.objects.get_role_permissions(role, project)['can_change_project_settings']:
            tasks = ProjectTask.objects.get_project_tasks(project).values()
            return JsonResponse({'status': 'succes','tasks':list(tasks)})
        else:
            return JsonResponse({'status': 'Unauthorized access', 'code': 403})
    except Exception as e:
        print(str(e))
        return JsonResponse({'status': str(e), 'code': 404})
@csrf_exempt
@require_http_methods(["POST"])
def api_add_project_task(request,name):
    try:
        data = json.loads(request.body)
        project = Project.objects.get(name=name)
        if project is None:
            return JsonResponse({'status':'Error','message':'Project does not exist','code':404})
        title = data.get('title')
        description = data.get('description')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        return ProjectTask.objects.add_task_to_project(project,title,description,start_date,end_date)
    except Exception as e:
        print(str(e))
@csrf_exempt
@require_http_methods(["DELETE"])
def api_remove_project_tasks(request,name):
    try:
        project = Project.objects.get(name=name)
        role = UserProjectRole.objects.get_user_role_in_project(project, request.user)
        if UserProjectRole.objects.get_role_permissions(role, project)['can_change_project_settings']:
            data = json.loads(request.body)
            requirements = data.get('removedTasks', [])
            ProjectTask.objects.remove_tasks_from_project(requirements)
            return JsonResponse({'status':'succes','message':200})
        else:
            return JsonResponse({'status': 'Unauthorized access', 'code': 403})
    except Exception as e:
        return JsonResponse({'status':'error','message':str(e),'code':405})


@login_required
@require_http_methods(["GET"])
@ratelimit(key='user_or_ip', rate='10000/s', method='GET')
def api_get_project_roles(request, name):
    try:
        project = Project.objects.get(name=name)
        role = UserProjectRole.objects.get_user_role_in_project(project, request.user)

        if UserProjectRole.objects.get_role_permissions(role, project)['can_change_project_settings']:
            project_roles = list(ProjectRole.objects.get_project_roles(project).values())
            for role_dict in project_roles:
                user_roles_entries = UserProjectRole.objects.filter(
                    project=project,
                    role_id=role_dict['id']
                ).select_related('user')

                role_dict['users'] = [entry.user.username for entry in user_roles_entries]

            return JsonResponse({'status': 'success', 'roles': project_roles}, status=200)
        else:
            return JsonResponse({'status': 'Unauthorized access'}, status=403)

    except Project.DoesNotExist:
        return JsonResponse({'status': 'Project not found'}, status=404)
    except Exception as e:
        print(f"Eroare in api_get_project_roles: {str(e)}")
        return JsonResponse({'status': 'error'}, status=500)

@login_required
def filter_tree_by_path(request,tree, current_path):
    result = []
    for item in tree:
        item_path = item['path']

        if current_path == "":
            if '/' not in item_path:
                result.append(item)
        else:
            if item_path.startswith(current_path + '/'):
                sub_path = item_path[len(current_path) + 1:]
                if '/' not in sub_path:
                    result.append(item)
    return result

@login_required
def handle_file_content(request,owner, repo, path):
    cache_key = f"github_file_{owner}_{repo}_{path.replace('/', '_')}"
    cached_file = cache.get(cache_key)
    if cached_file:
        return JsonResponse(cached_file, safe=False)

    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    headers = {"Accept": "application/vnd.github.v3+json"}
    if hasattr(settings, 'GITHUB_TOKEN'):
        headers["Authorization"] = f"token {settings.GITHUB_TOKEN}"

    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        cache.set(cache_key, r.json(), timeout=3600)
        return JsonResponse(r.json(), safe=False)
    return JsonResponse(r.json(), status=r.status_code, safe=False)
@login_required
def invalidate_repo_cache(repo:str,owner:str):
    try:
        print(len([k for k in cache.keys("*") if (repo in k and owner in k)]))
        print("-"*30)
    except Exception as e:
        print(str(e))
@login_required
def github_proxy_view(request, owner, repo, path=""):
    #invalidate_repo_cache(repo,owner)
    if path != "" and '.' in path.split('/')[-1]:
        return handle_file_content(request,owner, repo, path)

    branch = "main"
    cache_key = f"github_tree_recursive_{owner}_{repo}_{branch}"

    cached_tree = cache.get(cache_key)
    if cached_tree:
        return JsonResponse(filter_tree_by_path(request,cached_tree, path), safe=False)

    url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    headers = {"Accept": "application/vnd.github.v3+json"}
    if hasattr(settings, 'GITHUB_TOKEN'):
        headers["Authorization"] = f"token {settings.GITHUB_TOKEN}"

    response = requests.get(url, headers=headers)

    if response.status_code == 404 and branch == "main":
        url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/master?recursive=1"
        response = requests.get(url, headers=headers)

    if response.status_code != 200:
        return JsonResponse({'error': 'Nu am putut lua arborele'}, status=response.status_code)

    raw_tree = response.json().get('tree', [])

    formatted_tree = []
    for item in raw_tree:
        formatted_tree.append({
            'name': item['path'].split('/')[-1],
            'path': item['path'],
            'type': 'dir' if item['type'] == 'tree' else 'file'
        })
    cache.set(cache_key, formatted_tree, timeout=3600)
    return JsonResponse(filter_tree_by_path(request,formatted_tree, path), safe=False)
@login_required
@csrf_exempt
def proxy_run_code(request):
    if request.method != "POST":
        return JsonResponse({'error':'non post requests not allowed'},status=405)
    try:
        body = json.loads(request.body)
        source_code = body.get("source_code")
        language_id = body.get("language_id",71)

        if not source_code:
            return JsonResponse({'error':'Code fragment is empty'},status=400)
        url = settings.RAPIDAPI_URL
        headers = {
            'Content-Type':'application/json',
            'X-RapidAPI-Key':settings.RAPIDAPI_KEY,
            'X-RapidAPI-Host':settings.RAPIDAPI_HOST
        }
        payload = {
            'source_code':source_code,
            'language_id':language_id,
            'stdin':""
        }
        response = requests.post(url,json=payload,headers=headers)
        return JsonResponse(response.json(),status=response.status_code,safe=False)
    except Exception as e:
        return JsonResponse({'error':'Internal server error','message':str(e)},status=500)
@login_required
def request_file_open(request):
    pass
@login_required
@require_http_methods(["GET"])
def api_get_availible_languages(request):
    cache_key = "cache_key_availible_languages"
    if request.GET.get('invalidate') == 'true':
        cache.delete(cache_key)
    cached_languages = cache.get(cache_key)
    if cached_languages:
        return JsonResponse({'status': 'success', 'languages': cached_languages, 'source': 'cache'}, status=200)
    try:
        url = f"https://{settings.RAPIDAPI_HOST}/languages"
        headers = {
            'X-RapidAPI-Key': settings.RAPIDAPI_KEY,
            'X-RapidAPI-Host': settings.RAPIDAPI_HOST
        }
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            languages = response.json()

            cache.set(cache_key, languages, timeout=604800)

            return JsonResponse({'status': 'success', 'languages': languages, 'source': 'api'}, status=200)
    except Exception as e:
        return JsonResponse({'status':'error','message':str(e)},status=500)
@login_required
@require_http_methods(["POST"])
def verify_push_permissions(request,project,file_list):
    user = request.user
    role = UserProjectRole.objects.get_user_role_in_project(project,user)
    if role == 'visitor':
        raise ValueError('Visitor cannot push into a project')
    if not UserProjectRole.objects.get_role_permissions(role,project)['can_modify_files']:
        raise ValueError('Visitor cannot modify files into the given project')
    for file_path in file_list:
        resource_access = ResourceAccess.objects.filter(project=project, resource_path=file_path).first()
        if not resource_access:
            continue#File doesn;t jhave sharing policies set up
        if not request.user in resource_access.managers.all():
            raise ValueError(f'User cannot change file located at {file_path}')
@login_required
@require_http_methods(["POST"])
def push_files(request):
    #invalidate_repo_cache()
    try:
        data = json.loads(request.body)
        files = data.get('files',{})
        project = data.get('project')
        verify_push_permissions(request,project,files)
        repo = data.get('repo')
        owner = data.get('owner')
        branch = data.get('branch')
        default_msg = data.get('message','')
        if default_msg is None or default_msg == '':
            return JsonResponse({'error':'cannot push with no message'},status=400)
        message = f'[Pushed via GitSync]:{default_msg}'

        headers = {
            "Authorization": f"token {settings.GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }

        errors = []
        for path, content in files.items():
            url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={branch}"
            sha = None

            meta_res = requests.get(f"{url}", headers=headers)
            if meta_res.status_code == 200:
                sha = meta_res.json().get('sha')

            encoded_content = base64.b64encode(content.encode('utf-8')).decode('utf-8')

            put_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
            payload = {
                "message": message,
                "content": encoded_content,
                "branch": branch
            }
            if sha:
                payload["sha"] = sha

            put_res = requests.put(put_url, json=payload, headers=headers)

            if put_res.status_code in [200, 201]:
                cache_key = f"file_content_{owner}_{repo}_{branch}_{path}"
                cache.set(cache_key, content, timeout=3600)
            if errors:
                errors.append({'path':path,'error': put_res.json()})

            cache.delete(f"repo_tree_{owner}_{repo}")
            if errors:
                return JsonResponse({'status': 'partial_error', 'errors': errors}, status=400)
            return JsonResponse({'status': 'success'})
    except Exception as e:
        print(str(e))
        return JsonResponse({'error':str(e)},status=500)

@login_required
@require_http_methods(["POST"])
@csrf_exempt
def api_add_project_role(request, project_id):
    try:
        project = get_object_or_404(Project, id=project_id)
        user_role = UserProjectRole.objects.get_user_role_in_project(project, request.user)
        if UserProjectRole.objects.get_role_permissions(user_role, project)['can_change_project_settings']:
            data = json.loads(request.body)
            can_accept_invites = data.get('can_accept_invites', False),
            can_invite_others = data.get('can_invite_others', False),
            can_kick_others = data.get('can_kick_others', False),
            can_change_roles = data.get('can_change_roles', False),
            can_start_calls = data.get('can_start_calls', False),
            can_add_tasks = data.get('can_add_tasks', False),
            can_delete_tasks = data.get('can_delete_tasks', False),
            can_modify_tasks = data.get('can_modify_tasks', False),
            can_change_project_settings = data.get('can_change_project_settings', False)
            if can_accept_invites and can_invite_others and can_kick_others and can_change_roles and can_start_calls and can_add_tasks and can_modify_tasks and can_delete_tasks and can_change_project_settings:
                return JsonResponse({'error':'Cannot recreate the owner role'},status=403)
            new_role = ProjectRole.objects.create(
                project=project,
                name=data.get('name'),
                can_accept_invites=can_accept_invites,
                can_invite_others=can_invite_others,
                can_kick_others=can_kick_others,
                can_change_roles=can_change_roles,
                can_start_calls=can_start_calls,
                can_add_tasks=can_add_tasks,
                can_delete_tasks=can_delete_tasks,
                can_modify_tasks=can_modify_tasks,
                can_change_project_settings=can_change_project_settings
            )
            return JsonResponse({'status': 'success', 'role_id': new_role.id}, status=200)
        else:
            return JsonResponse({'status': 'Unauthorized access'}, status=403)

    except Exception as e:
        print(f"Eroare in api_add_project_role: {str(e)}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@login_required
@require_http_methods(["POST"])
@csrf_exempt
def api_assign_users_to_role(request, id):
    try:
        project = get_object_or_404(Project,id=id)
        user_role = UserProjectRole.objects.get_user_role_in_project(project, request.user)

        if UserProjectRole.objects.get_role_permissions(user_role, project)['can_change_project_settings']:
            data = json.loads(request.body)
            role_id = data.get('role_id')
            usernames = data.get('usernames', [])

            target_role = get_object_or_404(ProjectRole, id=role_id, project=project)

            assigned_users = []

            for username in usernames:
                try:
                    target_user = User.objects.get(username=username)

                    existing_roles = UserProjectRole.objects.filter(project=project, user=target_user)
                    if existing_roles.exists():
                        existing_roles.delete()

                    UserProjectRole.objects.create(project=project, user=target_user, role=target_role)
                    assigned_users.append(username)

                except User.DoesNotExist:
                    print(f"Userul {username} nu exista in baza de date, il sarim.")
                    continue

            return JsonResponse({'status': 'success', 'assigned': assigned_users}, status=200)
        else:
            return JsonResponse({'status': 'Unauthorized access'}, status=403)

    except Exception as e:
        print(f"Eroare in api_assign_users_to_role: {str(e)}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@login_required
@require_http_methods(["POST"])
@csrf_exempt
def api_share_file_access(request, name):
    try:
        project = get_object_or_404(Project, name=name)
        project_owner = project.owner
        user_role = UserProjectRole.objects.get_user_role_in_project(project, request.user)

        data = json.loads(request.body)
        file_path = data.get('file_path')
        target_usernames = data.get('usernames', [])
        give_management_rights = data.get('make_manager', False)

        can_modify_files = UserProjectRole.objects.get_role_permissions(user_role, project)['can_modify_files']

        resource_access = ResourceAccess.objects.filter(project=project, resource_path=file_path).first()
        is_file_manager = resource_access and request.user in resource_access.managers.all()

        if not (can_modify_files or is_file_manager):
            return JsonResponse({'status': 'Unauthorized', 'message': 'You do not have the right to share this file'},status=403)
        if not resource_access:
            resource_access = ResourceAccess.objects.create(project=project, resource_path=file_path)
            resource_access.managers.add(request.user)
            resource_access.managers.add(project_owner)
            resource_access.allowed_users.add(project_owner)
            resource_access.allowed_users.add(request.user)
        success_shared = []
        for username in target_usernames:
            try:
                user_to_add = User.objects.get(username=username)
                resource_access.allowed_users.add(user_to_add)
                if give_management_rights:
                    resource_access.managers.add(user_to_add)
                success_shared.append(username)
            except User.DoesNotExist:
                continue
        return JsonResponse({'status': 'success', 'shared_with': success_shared}, status=200)
    except Exception as e:
        print(f"Eroare in api_share_file_access: {str(e)}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@login_required
@require_POST
def api_request_project_join(request, project_id):
    try:
        project = get_object_or_404(Project, id=project_id)
        if UserProjectRole.objects.filter(user=request.user, project=project).exists():
            return JsonResponse({'status': 'error', 'message': 'Already member of this project.'}, status=400)
        pending_exists = UserRequest.objects.filter(
            sender=request.user,
            request_type='project',
            status='pending'
        ).exists()
        if pending_exists:
            return JsonResponse({'status': 'error', 'message': 'Already requested to join this project.'}, status=400)
        project_admins = User.objects.filter(
            user__project=project,
            user__role__can_change_project_settings=True
        ).distinct()
        if not project_admins.exists():
            return JsonResponse({'status': 'error', 'message': 'Project has no registered admins'}, status=500)
        UserRequest.objects.send_project_join_request(request.user,list(project_admins))
        return JsonResponse({'status': 'success', 'message': 'Request succesfully sent!'},status=200)

    except Project.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Project does not exist.'}, status=404)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
@login_required
@require_POST
def api_handle_project_join_request(request, request_id):
    try:
        # Extragem decizia din body (ex: {"action": "accept"})
        data = json.loads(request.body)
        action = data.get('action')

        user_req = get_object_or_404(UserRequest, id=request_id, request_type='project', status='pending')

        if isinstance(user_req,QuerySet):
            checked = list(user_req)[0]
            project_admin = checked.receiver
        # Opțional: Aici ar trebui să te asiguri că request.user are dreptul să accepte (e admin pe proiectul vizat)
        # Presupunem că target_object_id e ID-ul proiectului pentru cererile de tip 'project'
        project = get_object_or_404(Project, id=user_req.target_object_id)

        if action == 'accept':
            UserProjectRole.objects.create(
                user=user_req.sender,
                project=project,
                # role=default_role
            )
            user_req.status = 'accepted'
            user_req.save()
            return JsonResponse({'status': 'success', 'message': 'User accepted into project.'}, status=200)
        elif action == 'reject':
            user_req.status = 'rejected'
            user_req.save()
            return JsonResponse({'status': 'success', 'message': 'Request denied.'}, status=200)
        else:
            return JsonResponse({'status': 'error', 'message': 'Invalid action provided.'}, status=400)
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON body.'}, status=400)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)