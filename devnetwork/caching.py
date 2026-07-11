from abc import ABC, abstractmethod
from enum import Enum

from django.core.cache import cache as django_cache


class CacheManager(ABC):
    """
    Backend-agnostic cache interface. django.core.cache.cache already works
    against Redis/Memcached/LocMem interchangeably for get/set/delete, so
    those are thin passthroughs here. delete_pattern is the one operation
    that genuinely differs per backend (wildcard key scanning is a Redis-only
    concept), which is why it's the one method every backend must implement
    for itself instead of sharing a single implementation.
    """
    @abstractmethod
    def get(self, key, default=None):
        ...
    @abstractmethod
    def set(self, key, value, timeout=None):
        ...
    @abstractmethod
    def delete(self, key):
        ...
    @abstractmethod
    def delete_many(self, keys):
        ...
    @abstractmethod
    def delete_pattern(self, pattern):
        """Deletes every key matching a glob-style pattern (e.g. 'github_file_owner_repo_*')."""
        ...


class RedisCacheManager(CacheManager):
    """Current backend: django-redis on top of Django's cache framework."""
    def get(self, key, default=None):
        return django_cache.get(key, default)
    def set(self, key, value, timeout=None):
        django_cache.set(key, value, timeout=timeout)
    def delete(self, key):
        django_cache.delete(key)
    def delete_many(self, keys):
        if keys:
            django_cache.delete_many(keys)
    def delete_pattern(self, pattern):
        matched_keys = list(django_cache.keys(pattern))
        if matched_keys:
            django_cache.delete_many(matched_keys)


cache_manager: CacheManager = RedisCacheManager()

class UserCacheKey(str, Enum):
    PROFILE_DATA = 'users:profile_data:{user_id}'
    PROFILE_SECTIONS = 'users:profile_sections:{user_id}'
    TECHSTACK = 'users:techstack:{user_id}'
    PROJECTS = 'users:projects:{user_id}'
    FRIENDSHIP_REQUESTS = 'users:friendship_requests:{user_id}'
    # Reserved for the future React-based inbox/notifications feature.
    # No manager method reads or writes this key yet.
    NOTIFICATIONS = 'users:notifications:{user_id}'


class ChatCacheKey(str, Enum):
    """
    All three are paginated and append-only (new messages/conversations never
    change older pages, they just get added past the end), so these are cached
    with a short TTL instead of write-triggered invalidation: exact invalidation
    would need to know every (page_number, page_size) combo a client ever used,
    which isn't predictable from the write side without pattern-based deletes.
    """
    USER_CONVERSATIONS = 'chat:users:{user_id}:conversations:{page_number}:{page_size}'
    PROJECT_CONVERSATIONS = 'chat:projects:{project_id}:conversations:{page_number}:{page_size}'
    CONVERSATION_MESSAGES = 'chat:conversations:{conversation_id}:messages:{page_number}:{page_size}'


class ProjectCacheKey(str, Enum):
    # Role name a specific user holds in a project. Invalidated whenever that
    # user's UserProjectRole row changes (reassignment, kick, join accepted).
    USER_ROLE = 'projects:{project_id}:users_roles:{user_id}'
    # Permission dict for a role NAME within a project - shared by every user
    # who holds that role, not duplicated per user. Invalidated on role creation
    # (there's no role-edit endpoint yet).
    ROLE_PERMISSIONS = 'projects:{project_id}:role_permissions:{role_name}'
    # One structure per project: list of {id, name, owner, repo, link} dicts.
    REPOS = 'projects:{project_id}:repos'