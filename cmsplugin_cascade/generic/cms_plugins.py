# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.conf import settings
from django.conf.urls import url
from django.forms import widgets
from django.http.response import HttpResponse, JsonResponse, HttpResponseNotFound
from django.template.loader import render_to_string
from django.utils.html import format_html, format_html_join
from django.utils.translation import ugettext_lazy as _
from django.utils.safestring import mark_safe

from cms.plugin_pool import plugin_pool
from cmsplugin_cascade.fields import GlossaryField
from cmsplugin_cascade.plugin_base import CascadePluginBase, TransparentContainer
from cmsplugin_cascade.models import IconFont
from cmsplugin_cascade.utils import resolve_dependencies
from cmsplugin_cascade.widgets import CascadingSizeWidget, SetBorderWidget, ColorPickerWidget


class SimpleWrapperPlugin(TransparentContainer, CascadePluginBase):
    name = _("Simple Wrapper")
    parent_classes = None
    require_parent = False
    allow_children = True
    alien_child_classes = True
    TAG_CHOICES = tuple((cls, _("<{}> – Element").format(cls))
        for cls in ('div', 'span', 'section', 'article',)) + (('naked', _("Naked Wrapper")),)

    tag_type = GlossaryField(
        widgets.Select(choices=TAG_CHOICES),
        label=_("HTML element tag"),
        help_text=_('Choose a tag type for this HTML element.')
    )

    @classmethod
    def get_identifier(cls, instance):
        identifier = super(SimpleWrapperPlugin, cls).get_identifier(instance)
        tag_name = dict(cls.TAG_CHOICES).get(instance.glossary.get('tag_type'))
        if tag_name:
            return format_html('{0} {1}', tag_name, identifier)
        return identifier

    def get_render_template(self, context, instance, placeholder):
        if instance.glossary.get('tag_type') == 'naked':
            return 'cascade/generic/naked.html'
        return 'cascade/generic/wrapper.html'

plugin_pool.register_plugin(SimpleWrapperPlugin)


class HorizontalRulePlugin(CascadePluginBase):
    name = _("Horizontal Rule")
    parent_classes = None
    allow_children = False
    tag_type = 'hr'
    render_template = 'cascade/generic/single.html'
    glossary_fields = ()

plugin_pool.register_plugin(HorizontalRulePlugin)


class HeadingPlugin(CascadePluginBase):
    name = _("Heading")
    parent_classes = None
    allow_children = False
    TAG_TYPES = tuple(('h{}'.format(k), _("Heading {}").format(k)) for k in range(1, 7))

    tag_type = GlossaryField(widgets.Select(choices=TAG_TYPES))

    content = GlossaryField(
        widgets.TextInput(attrs={'style': 'width: 350px; font-weight: bold; font-size: 125%;'}),
         _("Heading content"))

    render_template = 'cascade/generic/heading.html'

    class Media:
        css = {'all': ('cascade/css/admin/partialfields.css',)}

    @classmethod
    def get_identifier(cls, instance):
        identifier = super(HeadingPlugin, cls).get_identifier(instance)
        tag_type = instance.glossary.get('tag_type')
        content = instance.glossary.get('content')
        if tag_type:
            return format_html('<code>{0}</code>: {1} {2}', tag_type, content, identifier)
        return content

plugin_pool.register_plugin(HeadingPlugin)


class CustomSnippetPlugin(TransparentContainer, CascadePluginBase):
    """
    Allows to add a customized template anywhere. This plugins will be registered only if the
    project added a template using the configuration setting 'plugins_with_extra_render_templates'.
    """
    name = _("Custom Snippet")
    require_parent = False
    allow_children = True
    alien_child_classes = True
    render_template_choices = dict(settings.CMSPLUGIN_CASCADE['plugins_with_extra_render_templates'].get('CustomSnippetPlugin', ()))
    render_template = 'cascade/generic/does_not_exist.html'  # default in case the template could not be found

    @classmethod
    def get_identifier(cls, instance):
        render_template = instance.glossary.get('render_template')
        if render_template:
            return format_html('{}', cls.render_template_choices.get(render_template))

if CustomSnippetPlugin.render_template_choices:
    # register only, if at least one template has been defined
    plugin_pool.register_plugin(CustomSnippetPlugin)


class FontIconModelMixin(object):
    @property
    def icon_font_attrs(self):
        icon_font = self.plugin_class.get_icon_font(self)
        content = self.glossary.get('content')
        attrs = []
        if icon_font and content:
            attrs.append(mark_safe('class="{}{}"'.format(icon_font.config_data.get('css_prefix_text', 'icon-'), content)))
        styles = {
            'display': 'inline-block',
            'color': self.glossary.get('color', '#000000'),
        }
        disabled, background_color = self.glossary.get('background_color', (True, '#000000'))
        if not disabled:
            styles['background-color'] = background_color
        border = self.glossary.get('border')
        if isinstance(border, list) and border[1] != 'none':
            styles.update(border='{0} {1} {2}'.format(*border))
            radius = self.glossary.get('border_radius')
            if radius:
                styles['border-radius'] = radius
        attrs.append(format_html('style="{}"',
                                 format_html_join('', '{0}:{1};',
                                                  [(k , v) for k, v in styles.items()])))
        return mark_safe(' '.join(attrs))


class FontIconPluginMixin(object):
    change_form_template = 'cascade/admin/fonticon_plugin_change_form.html'

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        extra_context = dict(extra_context or {}, icon_fonts=IconFont.objects.all())
        return super(FontIconPluginMixin, self).changeform_view(
             request, object_id=object_id, form_url=form_url, extra_context=extra_context)

    def get_form(self, request, obj=None, **kwargs):
        icon_font_field = [gf for gf in self.glossary_fields if gf.name == 'icon_font'][0]
        icon_font_field.widget.choices = IconFont.objects.values_list('id', 'identifier')
        form = super(FontIconPluginMixin, self).get_form(request, obj=obj, **kwargs)
        return form

    def get_plugin_urls(self):
        urlpatterns = [
            url(r'^fetch_fonticons/(?P<iconfont_id>[0-9]+)$', self.fetch_fonticons),
            url(r'^fetch_fonticons/$', self.fetch_fonticons, name='fetch_fonticons'),
        ]
        urlpatterns.extend(super(FontIconPluginMixin, self).get_plugin_urls())
        return urlpatterns

    def fetch_fonticons(self, request, iconfont_id=None):
        try:
            icon_font = IconFont.objects.get(id=iconfont_id)
        except IconFont.DoesNotExist:
            return HttpResponseNotFound("IconFont with id={} does not exist".format(iconfont_id))
        else:
            data = dict(icon_font.config_data)
            data.pop('glyphs', None)
            data['families'] = icon_font.get_icon_families()
            return JsonResponse(data)

    @classmethod
    def get_icon_font(self, instance):
        if not hasattr(instance, '_cached_icon_font'):
            try:
                instance._cached_icon_font = IconFont.objects.get(id=instance.glossary.get('icon_font'))
            except IconFont.DoesNotExist:
                instance._cached_icon_font = None
        return instance._cached_icon_font


class FontIconPlugin(FontIconPluginMixin, CascadePluginBase):
    name = _("Font Icon")
    parent_classes = None
    require_parent = False
    allow_children = False
    render_template = 'cascade/generic/fonticon.html'
    model_mixins = (FontIconModelMixin,)
    SIZE_CHOICES = [('{}em'.format(c), "{} em".format(c)) for c in range(1, 13)]
    RADIUS_CHOICES = [(None, _("Square"))] + \
        [('{}px'.format(r), "{} px".format(r)) for r in (1, 2, 3, 5, 7, 10, 15, 20)] + \
        [('50%', _("Circle"))]

    icon_font = GlossaryField(
        widgets.Select(),
        label=_("Font"),
    )

    content = GlossaryField(
        widgets.HiddenInput(),
        label=_("Select Icon"),
    )

    font_size = GlossaryField(
        CascadingSizeWidget(allowed_units=['px', 'em']),
        label=_("Icon Size"),
        initial='1em',
    )

    color = GlossaryField(
        widgets.TextInput(attrs={'style': 'width: 5em;', 'type': 'color'}),
        label=_("Icon color"),
    )

    background_color = GlossaryField(
        ColorPickerWidget(),
        label=_("Background color"),
    )

    text_align = GlossaryField(
        widgets.RadioSelect(
            choices=(('', _("Do not align")), ('text-left', _("Left")),
                     ('text-center', _("Center")), ('text-right', _("Right")))),
        label=_("Text Align"),
        initial='',
        help_text=_("Align the icon inside the parent column.")
    )

    border = GlossaryField(
        SetBorderWidget(),
        label=_("Set border"),
    )

    border_radius = GlossaryField(
        widgets.Select(choices=RADIUS_CHOICES),
        label=_("Border radius"),
    )

    glossary_field_order = ('icon_font', 'content', 'font_size', 'color', 'background_color',
                            'text_align', 'border', 'border_radius')

    class Media:
        css = {'all': ('cascade/css/admin/fonticonplugin.css',)}
        js = resolve_dependencies('cascade/js/admin/fonticonplugin.js')

    @classmethod
    def get_identifier(cls, instance):
        identifier = super(FontIconPlugin, cls).get_identifier(instance)
        icon_font = cls.get_icon_font(instance)
        if icon_font:
            content = mark_safe('{}: <i class="{}{}"></i>'.format(
                icon_font.identifier,
                icon_font.config_data.get('css_prefix_text', 'icon-'),
                instance.glossary.get('content')))
            return format_html('{0}{1}', identifier, content)
        return identifier

    @classmethod
    def get_tag_type(self, instance):
        if instance.glossary.get('text_align'):
            return 'div'

    @classmethod
    def get_css_classes(cls, instance):
        css_classes = super(FontIconPlugin, cls).get_css_classes(instance)
        text_align = instance.glossary.get('text_align')
        if text_align:
            css_classes.append(text_align)
        return css_classes

    @classmethod
    def get_inline_styles(cls, instance):
        inline_styles = super(FontIconPlugin, cls).get_inline_styles(instance)
        inline_styles['font-size'] = instance.glossary.get('font_size', '1em')
        return inline_styles

    def render(self, context, instance, placeholder):
        context['instance'] = instance
        icon_font = self.get_icon_font(instance)
        if icon_font:
            context['stylesheet_url'] = icon_font.get_stylesheet_url()
        return context

plugin_pool.register_plugin(FontIconPlugin)


class TextIconModelMixin(object):
    @property
    def icon_font_class(self):
        icon_font = self.plugin_class.get_icon_font(self)
        content = self.glossary.get('content')
        if icon_font and content:
            return mark_safe('class="{}{}"'.format(icon_font.config_data.get('css_prefix_text', 'icon-'), content))
        return ''


class TextIconPlugin(FontIconPluginMixin, CascadePluginBase):
    name = _("Icon")
    text_enabled = True
    render_template = 'cascade/generic/texticon.html'
    parent_classes = ('TextPlugin',)
    model_mixins = (TextIconModelMixin,)
    allow_children = False
    require_parent = False

    icon_font = GlossaryField(
        widgets.Select(),
        label=_("Font"),
    )

    content = GlossaryField(
        widgets.HiddenInput(),
        label=_("Select Icon"),
    )

    glossary_field_order = ('icon_font', 'content')

    class Media:
        css = {'all': ('cascade/css/admin/fonticonplugin.css',)}
        js = resolve_dependencies('cascade/js/admin/fonticonplugin.js')

    @classmethod
    def requires_parent_plugin(cls, slot, page):
        return False

    def render(self, context, instance, placeholder):
        context = super(TextIconPlugin, self).render(context, instance, placeholder)
        context['in_edit_mode'] = self.in_edit_mode(context['request'], instance.placeholder)
        return context

    def get_plugin_urls(self):
        urls = [
            url(r'^wysiwig-config.js$', self.render_wysiwig_config,
                name='cascade_texticon_wysiwig_config'),
        ]
        return urls

    def render_wysiwig_config(self, request):
        context = {
            'icon_fonts': IconFont.objects.all()
        }
        javascript = render_to_string('cascade/admin/ckeditor.wysiwyg.js', context)
        return HttpResponse(javascript, content_type='application/javascript')

plugin_pool.register_plugin(TextIconPlugin)
