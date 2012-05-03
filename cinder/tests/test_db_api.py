# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Unit tests for the DB API"""

from cinder import test
from cinder import context
from cinder import db
from cinder import exception
from cinder import flags

FLAGS = flags.FLAGS


def _get_fake_aggr_values():
    return {'name': 'fake_aggregate',
            'availability_zone': 'fake_avail_zone', }


def _get_fake_aggr_metadata():
    return {'fake_key1': 'fake_value1',
            'fake_key2': 'fake_value2'}


def _get_fake_aggr_hosts():
    return ['foo.openstack.org']


def _create_aggregate(context=context.get_admin_context(),
                      values=_get_fake_aggr_values(),
                      metadata=_get_fake_aggr_metadata()):
    return db.aggregate_create(context, values, metadata)


def _create_aggregate_with_hosts(context=context.get_admin_context(),
                      values=_get_fake_aggr_values(),
                      metadata=_get_fake_aggr_metadata(),
                      hosts=_get_fake_aggr_hosts()):
    result = _create_aggregate(context=context,
                               values=values, metadata=metadata)
    for host in hosts:
        db.aggregate_host_add(context, result.id, host)
    return result


class AggregateDBApiTestCase(test.TestCase):
    def setUp(self):
        super(AggregateDBApiTestCase, self).setUp()
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)

    def test_aggregate_create(self):
        """Ensure aggregate can be created with no metadata."""
        result = _create_aggregate(metadata=None)
        self.assertEqual(result['operational_state'], 'created')

    def test_aggregate_create_avoid_name_conflict(self):
        """Test we can avoid conflict on deleted aggregates."""
        r1 = _create_aggregate(metadata=None)
        db.aggregate_delete(context.get_admin_context(), r1.id)
        values = {'name': r1.name, 'availability_zone': 'new_zone'}
        r2 = _create_aggregate(values=values)
        self.assertEqual(r2.name, values['name'])
        self.assertEqual(r2.availability_zone, values['availability_zone'])
        self.assertEqual(r2.operational_state, "created")

    def test_aggregate_create_raise_exist_exc(self):
        """Ensure aggregate names are distinct."""
        _create_aggregate(metadata=None)
        self.assertRaises(exception.AggregateNameExists,
                          _create_aggregate, metadata=None)

    def test_aggregate_get_raise_not_found(self):
        """Ensure AggregateNotFound is raised when getting an aggregate."""
        ctxt = context.get_admin_context()
        # this does not exist!
        aggregate_id = 1
        self.assertRaises(exception.AggregateNotFound,
                          db.aggregate_get,
                          ctxt, aggregate_id)

    def test_aggregate_metadata_get_raise_not_found(self):
        """Ensure AggregateNotFound is raised when getting metadata."""
        ctxt = context.get_admin_context()
        # this does not exist!
        aggregate_id = 1
        self.assertRaises(exception.AggregateNotFound,
                          db.aggregate_metadata_get,
                          ctxt, aggregate_id)

    def test_aggregate_create_with_metadata(self):
        """Ensure aggregate can be created with metadata."""
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt)
        expected_metadata = db.aggregate_metadata_get(ctxt, result['id'])
        self.assertDictMatch(expected_metadata, _get_fake_aggr_metadata())

    def test_aggregate_create_low_privi_context(self):
        """Ensure right context is applied when creating aggregate."""
        self.assertRaises(exception.AdminRequired,
                          db.aggregate_create,
                          self.context, _get_fake_aggr_values())

    def test_aggregate_get(self):
        """Ensure we can get aggregate with all its relations."""
        ctxt = context.get_admin_context()
        result = _create_aggregate_with_hosts(context=ctxt)
        expected = db.aggregate_get(ctxt, result.id)
        self.assertEqual(_get_fake_aggr_hosts(), expected.hosts)
        self.assertEqual(_get_fake_aggr_metadata(), expected.metadetails)

    def test_aggregate_get_by_host(self):
        """Ensure we can get an aggregate by host."""
        ctxt = context.get_admin_context()
        r1 = _create_aggregate_with_hosts(context=ctxt)
        r2 = db.aggregate_get_by_host(ctxt, 'foo.openstack.org')
        self.assertEqual(r1.id, r2.id)

    def test_aggregate_get_by_host_not_found(self):
        """Ensure AggregateHostNotFound is raised with unknown host."""
        ctxt = context.get_admin_context()
        _create_aggregate_with_hosts(context=ctxt)
        self.assertRaises(exception.AggregateHostNotFound,
                          db.aggregate_get_by_host, ctxt, 'unknown_host')

    def test_aggregate_delete_raise_not_found(self):
        """Ensure AggregateNotFound is raised when deleting an aggregate."""
        ctxt = context.get_admin_context()
        # this does not exist!
        aggregate_id = 1
        self.assertRaises(exception.AggregateNotFound,
                          db.aggregate_delete,
                          ctxt, aggregate_id)

    def test_aggregate_delete(self):
        """Ensure we can delete an aggregate."""
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt, metadata=None)
        db.aggregate_delete(ctxt, result['id'])
        expected = db.aggregate_get_all(ctxt)
        self.assertEqual(0, len(expected))
        aggregate = db.aggregate_get(ctxt.elevated(read_deleted='yes'),
                                     result['id'])
        self.assertEqual(aggregate["operational_state"], "dismissed")

    def test_aggregate_update(self):
        """Ensure an aggregate can be updated."""
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt, metadata=None)
        new_values = _get_fake_aggr_values()
        new_values['availability_zone'] = 'different_avail_zone'
        updated = db.aggregate_update(ctxt, 1, new_values)
        self.assertNotEqual(result.availability_zone,
                            updated.availability_zone)

    def test_aggregate_update_with_metadata(self):
        """Ensure an aggregate can be updated with metadata."""
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt, metadata=None)
        values = _get_fake_aggr_values()
        values['metadata'] = _get_fake_aggr_metadata()
        db.aggregate_update(ctxt, 1, values)
        expected = db.aggregate_metadata_get(ctxt, result.id)
        self.assertDictMatch(_get_fake_aggr_metadata(), expected)

    def test_aggregate_update_with_existing_metadata(self):
        """Ensure an aggregate can be updated with existing metadata."""
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt)
        values = _get_fake_aggr_values()
        values['metadata'] = _get_fake_aggr_metadata()
        values['metadata']['fake_key1'] = 'foo'
        db.aggregate_update(ctxt, 1, values)
        expected = db.aggregate_metadata_get(ctxt, result.id)
        self.assertDictMatch(values['metadata'], expected)

    def test_aggregate_update_raise_not_found(self):
        """Ensure AggregateNotFound is raised when updating an aggregate."""
        ctxt = context.get_admin_context()
        # this does not exist!
        aggregate_id = 1
        new_values = _get_fake_aggr_values()
        self.assertRaises(exception.AggregateNotFound,
                          db.aggregate_update, ctxt, aggregate_id, new_values)

    def test_aggregate_get_all(self):
        """Ensure we can get all aggregates."""
        ctxt = context.get_admin_context()
        counter = 3
        for c in xrange(counter):
            _create_aggregate(context=ctxt,
                              values={'name': 'fake_aggregate_%d' % c,
                                      'availability_zone': 'fake_avail_zone'},
                              metadata=None)
        results = db.aggregate_get_all(ctxt)
        self.assertEqual(len(results), counter)

    def test_aggregate_get_all_non_deleted(self):
        """Ensure we get only non-deleted aggregates."""
        ctxt = context.get_admin_context()
        add_counter = 5
        remove_counter = 2
        aggregates = []
        for c in xrange(1, add_counter):
            values = {'name': 'fake_aggregate_%d' % c,
                      'availability_zone': 'fake_avail_zone'}
            aggregates.append(_create_aggregate(context=ctxt,
                                                values=values, metadata=None))
        for c in xrange(1, remove_counter):
            db.aggregate_delete(ctxt, aggregates[c - 1].id)
        results = db.aggregate_get_all(ctxt)
        self.assertEqual(len(results), add_counter - remove_counter)

    def test_aggregate_metadata_add(self):
        """Ensure we can add metadata for the aggregate."""
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt, metadata=None)
        metadata = _get_fake_aggr_metadata()
        db.aggregate_metadata_add(ctxt, result.id, metadata)
        expected = db.aggregate_metadata_get(ctxt, result.id)
        self.assertDictMatch(metadata, expected)

    def test_aggregate_metadata_update(self):
        """Ensure we can update metadata for the aggregate."""
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt)
        metadata = _get_fake_aggr_metadata()
        key = metadata.keys()[0]
        db.aggregate_metadata_delete(ctxt, result.id, key)
        new_metadata = {key: 'foo'}
        db.aggregate_metadata_add(ctxt, result.id, new_metadata)
        expected = db.aggregate_metadata_get(ctxt, result.id)
        metadata[key] = 'foo'
        self.assertDictMatch(metadata, expected)

    def test_aggregate_metadata_delete(self):
        """Ensure we can delete metadata for the aggregate."""
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt, metadata=None)
        metadata = _get_fake_aggr_metadata()
        db.aggregate_metadata_add(ctxt, result.id, metadata)
        db.aggregate_metadata_delete(ctxt, result.id, metadata.keys()[0])
        expected = db.aggregate_metadata_get(ctxt, result.id)
        del metadata[metadata.keys()[0]]
        self.assertDictMatch(metadata, expected)

    def test_aggregate_metadata_delete_raise_not_found(self):
        """Ensure AggregateMetadataNotFound is raised when deleting."""
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt)
        self.assertRaises(exception.AggregateMetadataNotFound,
                          db.aggregate_metadata_delete,
                          ctxt, result.id, 'foo_key')

    def test_aggregate_host_add(self):
        """Ensure we can add host to the aggregate."""
        ctxt = context.get_admin_context()
        result = _create_aggregate_with_hosts(context=ctxt, metadata=None)
        expected = db.aggregate_host_get_all(ctxt, result.id)
        self.assertEqual(_get_fake_aggr_hosts(), expected)

    def test_aggregate_host_add_deleted(self):
        """Ensure we can add a host that was previously deleted."""
        ctxt = context.get_admin_context()
        result = _create_aggregate_with_hosts(context=ctxt, metadata=None)
        host = _get_fake_aggr_hosts()[0]
        db.aggregate_host_delete(ctxt, result.id, host)
        db.aggregate_host_add(ctxt, result.id, host)
        expected = db.aggregate_host_get_all(ctxt, result.id)
        self.assertEqual(len(expected), 1)

    def test_aggregate_host_add_duplicate_raise_conflict(self):
        """Ensure we cannot add host to distinct aggregates."""
        ctxt = context.get_admin_context()
        _create_aggregate_with_hosts(context=ctxt, metadata=None)
        self.assertRaises(exception.AggregateHostConflict,
                          _create_aggregate_with_hosts, ctxt,
                          values={'name': 'fake_aggregate2',
                                  'availability_zone': 'fake_avail_zone2', },
                          metadata=None)

    def test_aggregate_host_add_duplicate_raise_exist_exc(self):
        """Ensure we cannot add host to the same aggregate."""
        ctxt = context.get_admin_context()
        result = _create_aggregate_with_hosts(context=ctxt, metadata=None)
        self.assertRaises(exception.AggregateHostExists,
                          db.aggregate_host_add,
                          ctxt, result.id, _get_fake_aggr_hosts()[0])

    def test_aggregate_host_add_raise_not_found(self):
        """Ensure AggregateFound when adding a host."""
        ctxt = context.get_admin_context()
        # this does not exist!
        aggregate_id = 1
        host = _get_fake_aggr_hosts()[0]
        self.assertRaises(exception.AggregateNotFound,
                          db.aggregate_host_add,
                          ctxt, aggregate_id, host)

    def test_aggregate_host_delete(self):
        """Ensure we can add host to the aggregate."""
        ctxt = context.get_admin_context()
        result = _create_aggregate_with_hosts(context=ctxt, metadata=None)
        db.aggregate_host_delete(ctxt, result.id,
                                 _get_fake_aggr_hosts()[0])
        expected = db.aggregate_host_get_all(ctxt, result.id)
        self.assertEqual(0, len(expected))

    def test_aggregate_host_delete_raise_not_found(self):
        """Ensure AggregateHostNotFound is raised when deleting a host."""
        ctxt = context.get_admin_context()
        result = _create_aggregate(context=ctxt)
        self.assertRaises(exception.AggregateHostNotFound,
                          db.aggregate_host_delete,
                          ctxt, result.id, _get_fake_aggr_hosts()[0])
