from django.template.defaulttags import register

@register.filter
def get_value(dictionary, key):
    return dictionary.get(key)

@register.filter
def mod24(s):
    n = int(s[:2])
    return f"{n % 24:02d}" + s[2:]
