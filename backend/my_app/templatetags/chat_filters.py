import markdown as md
from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter(name="render_markdown")
def render_markdown(text):
    html = md.markdown(text or "", extensions=["nl2br"])
    return mark_safe(html)
