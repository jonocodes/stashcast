from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.utils.html import format_html, mark_safe

from media.models import MediaItem
from media.tasks import generate_summary, process_media

DEMO_GROUP = 'DemoReadOnly'


def is_demo_readonly(user):
    return user.is_authenticated and user.groups.filter(name=DEMO_GROUP).exists()


class DemoReadOnlyAdminMixin:
    """
    Allows viewing change pages with normal UI, but blocks any POST that would write.
    """

    def has_module_permission(self, request):
        if is_demo_readonly(request.user):
            return True
        return super().has_module_permission(request)

    def has_add_permission(self, request):
        # Returning True keeps "Add" buttons visible in the app index/list pages.
        # They'll still be blocked on POST by add_view.
        return True

    def has_change_permission(self, request, obj=None):
        # True so they can open the change form and see Save buttons.
        return True

    def has_view_permission(self, request, obj=None):
        if is_demo_readonly(request.user):
            return True
        return super().has_view_permission(request, obj=obj)

    def has_delete_permission(self, request, obj=None):
        # True so delete UI can show, but delete_view will block POST.
        return True

    def add_view(self, request, form_url='', extra_context=None):
        if is_demo_readonly(request.user) and request.method == 'POST':
            raise PermissionDenied('Demo users are not allowed to add objects.')
        return super().add_view(request, form_url, extra_context)

    def change_view(self, request, object_id, form_url='', extra_context=None):
        if is_demo_readonly(request.user) and request.method == 'POST':
            raise PermissionDenied('Demo users are not allowed to change objects.')
        return super().change_view(request, object_id, form_url, extra_context)

    def delete_view(self, request, object_id, extra_context=None):
        if is_demo_readonly(request.user) and request.method == 'POST':
            raise PermissionDenied('Demo users are not allowed to delete objects.')
        return super().delete_view(request, object_id, extra_context)

    def get_actions(self, request):
        actions = super().get_actions(request)
        # Optional: keep actions visible if you want; but most actions write.
        # If you want them visible-but-fail, leave them. If you want to hide:
        if is_demo_readonly(request.user):
            # Prevent bulk delete and other write actions
            actions.pop('delete_selected', None)
            actions.pop('refetch_items', None)
            actions.pop('regenerate_summaries', None)
        return actions


@admin.register(MediaItem)
class MediaItemAdmin(admin.ModelAdmin, DemoReadOnlyAdminMixin):
    list_display = [
        'title',
        'action_links',
        'media_type',
        'status',
        # 'author',
        # 'publish_date',
        'file_size_display',
        'updated_at',
    ]

    list_filter = [
        'status',
        'media_type',
        'requested_type',
        'created_at',
        'downloaded_at',
    ]

    search_fields = [
        'title',
        'author',
        'source_url',
        'guid',
        'slug',
    ]

    readonly_fields = [
        'guid',
        'created_at',
        'updated_at',
        'downloaded_at',
        'preview_display',
        'log_display',
    ]

    fieldsets = [
        ('Identification', {'fields': ['guid', 'slug', 'source_url']}),
        ('Status', {'fields': ['status', 'error_message']}),
        (
            'Media Info',
            {
                'fields': [
                    'requested_type',
                    'media_type',
                    'title',
                    'author',
                    'description',
                    'publish_date',
                    'duration_seconds',
                ]
            },
        ),
        (
            'Files',
            {
                'fields': [
                    'content_path',
                    'thumbnail_path',
                    'subtitle_path',
                    'file_size',
                    'mime_type',
                ]
            },
        ),
        ('Processing', {'fields': ['ytdlp_args', 'ffmpeg_args']}),
        (
            'Metadata',
            {
                'fields': [
                    'extractor',
                    'external_id',
                    'webpage_url',
                ]
            },
        ),
        ('Summary', {'fields': ['summary']}),
        ('Logs & Preview', {'fields': ['log_display', 'preview_display']}),
        ('Timestamps', {'fields': ['created_at', 'updated_at', 'downloaded_at']}),
    ]

    actions = ['refetch_items', 'regenerate_summaries']

    def file_size_display(self, obj):
        if obj.file_size:
            size_mb = obj.file_size / (1024 * 1024)
            return f'{size_mb:.2f} MB'
        return '-'

    file_size_display.short_description = 'File Size'

    def action_links(self, obj):
        edit_url = reverse('item_detail', args=[obj.guid])
        links = [
            f'<a href="{edit_url}" alt="View" title="View">👁️</a>',
            f'<a href="{edit_url}" alt="Edit" title="Edit">✏️</a>',
        ]
        if obj.log_path:
            # Link to the admin change page with log anchor
            admin_url = reverse('admin:media_mediaitem_change', args=[obj.guid])
            links.append(f'<a href="{admin_url}#log" alt="Logs" title="Logs">📜</a>')
        return mark_safe(' '.join(links))

    action_links.short_description = 'Actions'

    def preview_display(self, obj):
        if obj.status != MediaItem.STATUS_READY:
            return '-'

        # Build thumbnail URL
        if obj.thumbnail_path:
            thumb_url = reverse('admin:media_mediaitem_change', args=[obj.guid])
            thumb_url = f'{thumb_url}#thumbnail'
            return format_html(
                '<img src="{}" width="100%" height="300" alt="Thumbnail" '
                'style="object-fit: contain; border-radius: 4px;">',
                thumb_url,
            )
        else:
            return '-'

    def log_display(self, obj):
        if not obj.log_path:
            return 'No log file'

        log_path = obj.get_absolute_log_path()
        if not log_path:
            return 'No log file'

        try:
            with open(log_path, 'r') as f:
                log_content = f.read()
            return format_html(
                '<a name="log"></a><pre style="background: #f5f5f5; padding: 10px; '
                'border-radius: 4px; max-height: 400px; overflow: auto;">{}</pre>',
                log_content,
            )
        except Exception as e:
            return f'Error reading log: {e}'

    log_display.short_description = 'Logs'

    def refetch_items(self, request, queryset):
        if is_demo_readonly(request.user):
            raise PermissionDenied('Demo users are not allowed to refetch items.')
        count = 0
        for item in queryset:
            item.status = MediaItem.STATUS_PREFETCHING
            item.error_message = ''
            item.save()
            process_media(item.guid)
            count += 1
        self.message_user(request, f'Re-fetching {count} items.')

    refetch_items.short_description = 'Re-fetch selected items'

    def regenerate_summaries(self, request, queryset):
        if is_demo_readonly(request.user):
            raise PermissionDenied('Demo users are not allowed to regenerate summaries.')
        count = 0
        for item in queryset:
            if item.subtitle_path:
                generate_summary(item.guid)
                count += 1
        self.message_user(request, f'Enqueued summary generation for {count} items.')

    regenerate_summaries.short_description = 'Regenerate summaries'
