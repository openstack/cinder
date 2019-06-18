# Copyright 2013 OpenStack Foundation
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

from cinder.api import extensions
from cinder.api.schemas import scheduler_hints
from cinder.api import validation


def create(req, body):
    attr = 'OS-SCH-HNT:scheduler_hints'
    if body.get(attr) is not None:
        scheduler_hints_body = dict.fromkeys((attr,), body.get(attr))

        @validation.schema(scheduler_hints.create)
        def _validate_scheduler_hints(req=None, body=None):
            # TODO(pooja_jadhav): The scheduler hints schema validation
            # should be moved to v3 volume schema directly and this module
            # should be deleted at the time of deletion of v2 version code.
            pass

        _validate_scheduler_hints(req=req, body=scheduler_hints_body)
        body['volume']['scheduler_hints'] = scheduler_hints_body.get(attr)
    return body


# NOTE: This class is added to include "OS-SCH-HNT" in the list extensions
# response and "OS-SCH-HNT" is still not loaded as a standard extension.
class Scheduler_hints(extensions.ExtensionDescriptor):
    """Pass arbitrary key/value pairs to the scheduler."""

    name = "SchedulerHints"
    alias = "OS-SCH-HNT"
    updated = "2013-04-18T00:00:00+00:00"
