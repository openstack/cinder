#    Copyright 2015 Intel Corp.
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

from oslo_utils import timeutils
from oslo_versionedobjects import fields

from cinder.db.sqlalchemy import models
from cinder import objects


def fake_service_orm(**updates):
    """Create a fake ORM service instance."""
    db_service = fake_db_service(**updates)
    service = models.Service(**db_service)
    return service


def fake_db_service(**updates):
    NOW = timeutils.utcnow().replace(microsecond=0)
    db_service = {
        'created_at': NOW,
        'updated_at': NOW,
        'deleted_at': None,
        'deleted': False,
        'id': 123,
        'host': 'fake-host',
        'binary': 'fake-service',
        'topic': 'fake-service-topic',
        'report_count': 1,
        'disabled': False,
        'disabled_reason': None,
        'modified_at': NOW,
    }

    for name, field in objects.Service.fields.items():
        if name in db_service:
            continue
        if field.nullable:
            db_service[name] = None
        elif field.default != fields.UnspecifiedDefault:
            db_service[name] = field.default
        else:
            raise Exception('fake_db_service needs help with %s.' % name)

    if updates:
        db_service.update(updates)

    return db_service


def fake_service_obj(context, **updates):
    return objects.Service._from_db_object(context, objects.Service(),
                                           fake_db_service(**updates))
