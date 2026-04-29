from django.template import Context, Template
from django.template.loader import get_template
from django.test import SimpleTestCase


class TransportTemplateFilterTests(SimpleTestCase):
    def test_transport_list_template_compiles(self):
        template = get_template('transport/transport_list.html')

        self.assertEqual(template.origin.template_name, 'transport/transport_list.html')

    def test_split_lines_filter_ignores_blank_lines(self):
        template = Template(
            '{% load finance_custom_filters %}'
            '{% for point in points|split_lines %}[{{ point }}]{% endfor %}'
        )

        rendered = template.render(Context({'points': " Gate A\n\nStage 2\r\n  "}))

        self.assertEqual(rendered, '[Gate A][Stage 2]')
