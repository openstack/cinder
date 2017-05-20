# Copyright (c) 2017 Red Hat, Inc.
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

import mock
import six

from cinder import manager
from cinder import objects
from cinder import test


class FakeManager(manager.CleanableManager):
    def __init__(self, service_id=None, keep_after_clean=False):
        if service_id:
            self.service_id = service_id
        self.keep_after_clean = keep_after_clean

    def _do_cleanup(self, ctxt, vo_resource):
        vo_resource.status += '_cleaned'
        vo_resource.save()
        return self.keep_after_clean


class TestManager(test.TestCase):
    @mock.patch('cinder.utils.set_log_levels')
    def test_set_log_levels(self, set_log_mock):
        service = manager.Manager()
        log_request = objects.LogLevel(prefix='sqlalchemy.', level='debug')
        service.set_log_levels(mock.sentinel.context, log_request)
        set_log_mock.assert_called_once_with(log_request.prefix,
                                             log_request.level)

    @mock.patch('cinder.utils.get_log_levels')
    def test_get_log_levels(self, get_log_mock):
        get_log_mock.return_value = {'cinder': 'DEBUG', 'cinder.api': 'ERROR'}
        service = manager.Manager()
        log_request = objects.LogLevel(prefix='sqlalchemy.')
        result = service.get_log_levels(mock.sentinel.context, log_request)
        get_log_mock.assert_called_once_with(log_request.prefix)

        expected = (objects.LogLevel(prefix='cinder', level='DEBUG'),
                    objects.LogLevel(prefix='cinder.api', level='ERROR'))

        self.assertEqual(set(six.text_type(r) for r in result.objects),
                         set(six.text_type(e) for e in expected))
