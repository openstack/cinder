# Copyright (c) 2016 Red Hat, Inc.
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

from oslo_utils import timeutils
from oslo_versionedobjects import fields

from cinder.db.sqlalchemy import models
from cinder import objects


def cluster_basic_fields():
    """Return basic fields for a cluster."""
    return {
        'id': 1,
        'created_at': timeutils.utcnow(with_timezone=False),
        'deleted': False,
        'name': 'cluster_name',
        'binary': 'cinder-volume',
        'race_preventer': 0,
    }


def fake_cluster_orm(**updates):
    """Create a fake ORM cluster instance."""
    db_cluster = fake_db_cluster(**updates)
    del db_cluster['services']
    cluster = models.Cluster(**db_cluster)
    return cluster


def fake_db_cluster(**updates):
    """Helper method for fake_cluster_orm.

    Creates a complete dictionary filling missing fields based on the Cluster
    field definition (defaults and nullable).
    """
    db_cluster = cluster_basic_fields()

    for name, field in objects.Cluster.fields.items():
        if name in db_cluster:
            continue
        if field.default != fields.UnspecifiedDefault:
            db_cluster[name] = field.default
        elif field.nullable:
            db_cluster[name] = None
        else:
            raise Exception('fake_db_cluster needs help with %s.' % name)

    if updates:
        db_cluster.update(updates)

    return db_cluster


def fake_cluster_ovo(context, **updates):
    """Create a fake Cluster versioned object."""
    return objects.Cluster._from_db_object(context, objects.Cluster(),
                                           fake_cluster_orm(**updates))
