# Copyright (c) 2018 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""Sphinx extension to be able to extract driver config options from code."""

import importlib

from docutils import nodes
from docutils.parsers import rst
from docutils.parsers.rst import directives
from docutils import statemachine as sm
from sphinx.util import logging
from oslo_config import cfg

LOG = logging.getLogger(__name__)


class ConfigTableDirective(rst.Directive):
    """Directive to extract config options into docs output."""

    option_spec = {
        'table-title': directives.unchanged,
        'config-target': directives.unchanged,
        'exclude-list': directives.unchanged,
        'exclusive-list': directives.unchanged,
    }

    has_content = True

    def _doc_module(self, module, filters, exclusive):
        """Extract config options from module."""
        options = []
        try:
            mod = importlib.import_module(module)
            for prop in dir(mod):
                # exclusive-list overrides others
                if exclusive and prop not in exclusive:
                    continue
                if prop in filters:
                    continue
                thing = getattr(mod, prop)
                if isinstance(thing, cfg.Opt) and thing not in options:
                    # An individual config option
                    options.append(thing)
                elif (isinstance(thing, list) and len(thing) > 0 and
                        isinstance(thing[0], cfg.Opt)):
                    # A list of config opts
                    options.extend(thing)
        except Exception as e:
            self.error('Unable to import {}: {}'.format(module, e))

        return options

    def _get_default(self, opt):
        """Tries to pick the best text to use as the default."""
        if hasattr(opt, 'sample_default') and opt.sample_default:
            return opt.sample_default

        if type(opt.default) == list:
            return "[%s]" % ', '.join(str(item) for item in opt.default)

        result = str(opt.default)
        if not result:
            result = '<>'
        return result

    def run(self):
        """Load and find config options to document."""
        modules = [c.strip() for c in self.content if c.strip()]

        if not modules:
            raise self.error('No modules provided to document.')

        env = self.state.document.settings.env
        app = env.app

        result = sm.ViewList()
        source = '<{}>'.format(__name__)

        target = self.options.get('config-target', '')
        title = self.options.get(
            'table-title',
            'Description of {} configuration options'.format(target))

        # See if there are option sets that need to be ignored
        exclude = self.options.get('exclude-list', '')
        exclude_list = [e.strip() for e in exclude.split(',') if e.strip()]

        exclusive = self.options.get('exclusive-list', '')
        exclusive_list = [e.strip() for e in exclusive.split(',') if e.strip()]

        result.append('.. _{}:'.format(title.replace(' ', '-')), source)
        result.append('', source)
        result.append('.. list-table:: {}'.format(title), source)
        result.append('   :header-rows: 1', source)
        result.append('   :class: config-ref-table', source)
        result.append('', source)
        result.append('   * - Configuration option = Default value', source)
        result.append('     - Description', source)

        options = []
        for module in modules:
            retval = self._doc_module(module, exclude_list, exclusive_list)
            if retval:
                options.extend(retval)
            else:
                LOG.info('[config-table] No options found in {}'.format(
                         module))

        # Get options sorted alphabetically but with deprecated options last
        list.sort(options, key=lambda opt: opt.name)
        list.sort(options, key=lambda opt: opt.deprecated_for_removal)

        for opt in options:
            result.append(
                '   * - ``{}`` = ``{}``'.format(
                    opt.name, self._get_default(opt)),
                source)
            result.append(
                '     - ({}) {}{}'.format(
                    opt.type, opt.help,
                    ' **DEPRECATED**' if opt.deprecated_for_removal else ''),
                source)

        node = nodes.section()
        node.document = self.state.document
        self.state.nested_parse(result, 0, node)
        return node.children


def setup(app):
    app.add_directive('config-table', ConfigTableDirective)
    return {
        'parallel_read_safe': True,
        'parallel_write_safe': True,
    }
