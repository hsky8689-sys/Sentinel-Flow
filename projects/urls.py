from django.urls import path

from projects.views import open_project_page, open_project_members_page, open_project_settings, api_get_project_domains, \
    api_get_project_requirements, api_add_project_domains, api_delete_project_domains, api_add_project_requirements, \
    api_remove_project_requirements, api_add_project_sections, api_remove_project_sections, api_get_project_tasks, \
    api_add_project_task, api_remove_project_tasks, api_get_project_roles, \
    github_proxy_view, proxy_run_code, push_files, api_add_project_role, api_assign_users_to_role, \
    api_get_availible_languages, api_request_project_join, api_handle_project_join_request

app_name = 'projects'

urlpatterns = [
    path("project-page/<str:name>/",open_project_page,name="project-page"),
    path("project-page/<str:name>/project-members/",open_project_members_page,name="project-members"),
    path("project-page/<str:name>/settings/",open_project_settings,name="project-settings"),
    path("api-get-project-domains",api_get_project_domains,name="get-project-domains"),
    path("settings/<str:name>/api-project-domains", api_get_project_domains, name="get-domains-from-settings"),
    path("<str:name>/api-get-project-requirements",api_get_project_requirements,name="get-requirements"),
    path("settings/<str:name>/api-get-project-requirements",api_get_project_requirements,name="get-requirements-from-settings"),
    path("settings/<str:name>/api-add-domains",api_add_project_domains,name="add-domains-to-project"),
    path("settings/<str:name>/api-remove-domains",api_delete_project_domains,name="add-domains-to-project"),
    path("settings/<str:name>/api-add-requirements",api_add_project_requirements,name="add-project-requirements"),
    path("settings/<str:name>/api-remove-requirements",api_remove_project_requirements,name="remove-project-requirements"),
    path("settings/<str:name>/api-add-requirement-sections",api_add_project_sections,name="add-project-requirement-sections"),
    path("settings/<str:name>/api-remove-requirement-sections",api_remove_project_sections,name="remove-project-requirement-sections"),
    path("settings/<str:name>/api-get-project-tasks",api_get_project_tasks,name="get_project_tasks"),
    path("settings/<str:name>/api-add-task",api_add_project_task,name="add-project-task"),
    path("settings/<str:name>/api-remove-tasks",api_remove_project_tasks,name="remove-project-tasks"),
    path("settings/<str:name>/api-get-roles",api_get_project_roles,name="remove-project-tasks"),
    path('api/github/<str:owner>/<str:repo>/',github_proxy_view,name='github-fetch-structure'),
    path('api/github/<str:owner>/<str:repo>/<path:path>',github_proxy_view,name='github-fetch-path'),
    path('api/run-code/',proxy_run_code,name='run-code'),
    path('api/github/push-files/',push_files,name='push-code'),
    path('settings/<int:id>/api-add-role', api_add_project_role,name="add-role"),
    path('/settings/<int:id>/defacutpemaine...',api_assign_users_to_role,name="add-users-to-role"),
    path('get-available-languages',api_get_availible_languages,name="view-selected-languages"),
    path('api/<int:project_id>/request-join',api_request_project_join,name='send-project-join-request'),
    path('api/requests/project/handle/',api_handle_project_join_request,name='handle-project-join-request')
]


