from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from media.models import MediaItem
from media.tasks import process_media, generate_summary


@admin.register(MediaItem)
class MediaItemAdmin(admin.ModelAdmin):
    list_display = [
        'title',
        'media_type',
        'status',
        'author',
        'publish_date',
        'file_size_display',
        'created_at',
        'action_links'
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
        'description',
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
        ('Identification', {
            'fields': ['guid', 'slug', 'source_url']
        }),
        ('Status', {
            'fields': ['status', 'error_message']
        }),
        ('Media Info', {
            'fields': [
                'requested_type',
                'media_type',
                'title',
                'author',
                'description',
                'publish_date',
                'duration_seconds',
            ]
        }),
        ('Files', {
            'fields': [
                'base_dir',
                'content_path',
                'thumbnail_path',
                'subtitle_path',
                'file_size',
                'mime_type',
            ]
        }),
        ('Processing', {
            'fields': ['ytdlp_args', 'ffmpeg_args']
        }),
        ('Metadata', {
            'fields': [
                'extractor',
                'external_id',
                'webpage_url',
            ]
        }),
        ('Summary', {
            'fields': ['summary']
        }),
        ('Logs & Preview', {
            'fields': ['log_display', 'preview_display']
        }),
        ('Timestamps', {
            'fields': ['created_at', 'updated_at', 'downloaded_at']
        }),
    ]

    actions = ['refetch_items', 'regenerate_summaries']

    def file_size_display(self, obj):
        if obj.file_size:
            size_mb = obj.file_size / (1024 * 1024)
            return f"{size_mb:.2f} MB"
        return "-"
    file_size_display.short_description = "File Size"

    def action_links(self, obj):
        view_url = reverse('item_detail', args=[obj.guid])
        links = [
            f'<a href="{view_url}" target="_blank">View</a>',
        ]
        if obj.log_path:
            links.append(f'<a href="#log">Logs</a>')
        return mark_safe(' | '.join(links))
    action_links.short_description = "Actions"

    def preview_display(self, obj):
        if obj.status != MediaItem.STATUS_READY:
            return "-"

        view_url = reverse('item_detail', args=[obj.guid])
        return format_html(
            '<iframe src="{}" width="100%" height="600" frameborder="0"></iframe>',
            view_url
        )
    preview_display.short_description = "Preview"

    def log_display(self, obj):
        if not obj.log_path:
            return "No log file"

        try:
            with open(obj.log_path, 'r') as f:
                log_content = f.read()
            return format_html(
                '<a name="log"></a><pre style="background: #f5f5f5; padding: 10px; '
                'border-radius: 4px; max-height: 400px; overflow: auto;">{}</pre>',
                log_content
            )
        except Exception as e:
            return f"Error reading log: {e}"
    log_display.short_description = "Logs"

    def refetch_items(self, request, queryset):
        count = 0
        for item in queryset:
            item.status = MediaItem.STATUS_PREFETCHING
            item.error_message = ''
            item.save()
            process_media(item.guid)
            count += 1
        self.message_user(request, f"Re-fetching {count} items.")
    refetch_items.short_description = "Re-fetch selected items"

    def regenerate_summaries(self, request, queryset):
        count = 0
        for item in queryset:
            if item.subtitle_path:
                generate_summary(item.guid)
                count += 1
        self.message_user(request, f"Enqueued summary generation for {count} items.")
    regenerate_summaries.short_description = "Regenerate summaries"
