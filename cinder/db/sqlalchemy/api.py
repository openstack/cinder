# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2014 IBM Corp.
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

"""Implementation of SQLAlchemy backend."""


import sys
import uuid
import warnings

from oslo.config import cfg
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_
from sqlalchemy.orm import joinedload, joinedload_all
from sqlalchemy.orm import RelationshipProperty
from sqlalchemy.sql.expression import literal_column
from sqlalchemy.sql import func

from cinder.common import sqlalchemyutils
from cinder.db.sqlalchemy import models
from cinder import exception
from cinder.openstack.common.db import exception as db_exc
from cinder.openstack.common.db.sqlalchemy import session as db_session
from cinder.openstack.common import log as logging
from cinder.openstack.common import timeutils
from cinder.openstack.common import uuidutils


CONF = cfg.CONF
LOG = logging.getLogger(__name__)

db_session.set_defaults(sql_connection='sqlite:///$state_path/$sqlite_db',
                        sqlite_db='cinder.sqlite')

get_engine = db_session.get_engine
get_session = db_session.get_session

_DEFAULT_QUOTA_NAME = 'default'


def get_backend():
    """The backend is this module itself."""

    return sys.modules[__name__]


def is_admin_context(context):
    """Indicates if the request context is an administrator."""
    if not context:
        warnings.warn(_('Use of empty request context is deprecated'),
                      DeprecationWarning)
        raise Exception('die')
    return context.is_admin


def is_user_context(context):
    """Indicates if the request context is a normal user."""
    if not context:
        return False
    if context.is_admin:
        return False
    if not context.user_id or not context.project_id:
        return False
    return True


def authorize_project_context(context, project_id):
    """Ensures a request has permission to access the given project."""
    if is_user_context(context):
        if not context.project_id:
            raise exception.NotAuthorized()
        elif context.project_id != project_id:
            raise exception.NotAuthorized()


def authorize_user_context(context, user_id):
    """Ensures a request has permission to access the given user."""
    if is_user_context(context):
        if not context.user_id:
            raise exception.NotAuthorized()
        elif context.user_id != user_id:
            raise exception.NotAuthorized()


def authorize_quota_class_context(context, class_name):
    """Ensures a request has permission to access the given quota class."""
    if is_user_context(context):
        if not context.quota_class:
            raise exception.NotAuthorized()
        elif context.quota_class != class_name:
            raise exception.NotAuthorized()


def require_admin_context(f):
    """Decorator to require admin request context.

    The first argument to the wrapped function must be the context.

    """

    def wrapper(*args, **kwargs):
        if not is_admin_context(args[0]):
            raise exception.AdminRequired()
        return f(*args, **kwargs)
    return wrapper


def require_context(f):
    """Decorator to require *any* user or admin context.

    This does no authorization for user or project access matching, see
    :py:func:`authorize_project_context` and
    :py:func:`authorize_user_context`.

    The first argument to the wrapped function must be the context.

    """

    def wrapper(*args, **kwargs):
        if not is_admin_context(args[0]) and not is_user_context(args[0]):
            raise exception.NotAuthorized()
        return f(*args, **kwargs)
    return wrapper


def require_volume_exists(f):
    """Decorator to require the specified volume to exist.

    Requires the wrapped function to use context and volume_id as
    their first two arguments.
    """

    def wrapper(context, volume_id, *args, **kwargs):
        volume_get(context, volume_id)
        return f(context, volume_id, *args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper


def require_snapshot_exists(f):
    """Decorator to require the specified snapshot to exist.

    Requires the wrapped function to use context and snapshot_id as
    their first two arguments.
    """

    def wrapper(context, snapshot_id, *args, **kwargs):
        snapshot_get(context, snapshot_id)
        return f(context, snapshot_id, *args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper


def model_query(context, *args, **kwargs):
    """Query helper that accounts for context's `read_deleted` field.

    :param context: context to query under
    :param session: if present, the session to use
    :param read_deleted: if present, overrides context's read_deleted field.
    :param project_only: if present and context is user-type, then restrict
            query to match the context's project_id.
    """
    session = kwargs.get('session') or get_session()
    read_deleted = kwargs.get('read_deleted') or context.read_deleted
    project_only = kwargs.get('project_only')

    query = session.query(*args)

    if read_deleted == 'no':
        query = query.filter_by(deleted=False)
    elif read_deleted == 'yes':
        pass  # omit the filter to include deleted and active
    elif read_deleted == 'only':
        query = query.filter_by(deleted=True)
    else:
        raise Exception(
            _("Unrecognized read_deleted value '%s'") % read_deleted)

    if project_only and is_user_context(context):
        query = query.filter_by(project_id=context.project_id)

    return query


def _sync_volumes(context, project_id, session, volume_type_id=None,
                  volume_type_name=None):
    (volumes, gigs) = _volume_data_get_for_project(
        context, project_id, volume_type_id=volume_type_id, session=session)
    key = 'volumes'
    if volume_type_name:
        key += '_' + volume_type_name
    return {key: volumes}


def _sync_snapshots(context, project_id, session, volume_type_id=None,
                    volume_type_name=None):
    (snapshots, gigs) = _snapshot_data_get_for_project(
        context, project_id, volume_type_id=volume_type_id, session=session)
    key = 'snapshots'
    if volume_type_name:
        key += '_' + volume_type_name
    return {key: snapshots}


def _sync_gigabytes(context, project_id, session, volume_type_id=None,
                    volume_type_name=None):
    (_junk, vol_gigs) = _volume_data_get_for_project(
        context, project_id, volume_type_id=volume_type_id, session=session)
    key = 'gigabytes'
    if volume_type_name:
        key += '_' + volume_type_name
    if CONF.no_snapshot_gb_quota:
        return {key: vol_gigs}
    (_junk, snap_gigs) = _snapshot_data_get_for_project(
        context, project_id, volume_type_id=volume_type_id, session=session)
    return {key: vol_gigs + snap_gigs}


QUOTA_SYNC_FUNCTIONS = {
    '_sync_volumes': _sync_volumes,
    '_sync_snapshots': _sync_snapshots,
    '_sync_gigabytes': _sync_gigabytes,
}


###################


@require_admin_context
def service_destroy(context, service_id):
    session = get_session()
    with session.begin():
        service_ref = _service_get(context, service_id, session=session)
        service_ref.delete(session=session)


@require_admin_context
def _service_get(context, service_id, session=None):
    result = model_query(
        context,
        models.Service,
        session=session).\
        filter_by(id=service_id).\
        first()
    if not result:
        raise exception.ServiceNotFound(service_id=service_id)

    return result


@require_admin_context
def service_get(context, service_id):
    return _service_get(context, service_id)


@require_admin_context
def service_get_all(context, disabled=None):
    query = model_query(context, models.Service)

    if disabled is not None:
        query = query.filter_by(disabled=disabled)

    return query.all()


@require_admin_context
def service_get_all_by_topic(context, topic):
    return model_query(
        context, models.Service, read_deleted="no").\
        filter_by(disabled=False).\
        filter_by(topic=topic).\
        all()


@require_admin_context
def service_get_by_host_and_topic(context, host, topic):
    result = model_query(
        context, models.Service, read_deleted="no").\
        filter_by(disabled=False).\
        filter_by(host=host).\
        filter_by(topic=topic).\
        first()
    if not result:
        raise exception.ServiceNotFound(service_id=None)
    return result


@require_admin_context
def service_get_all_by_host(context, host):
    return model_query(
        context, models.Service, read_deleted="no").\
        filter_by(host=host).\
        all()


@require_admin_context
def _service_get_all_topic_subquery(context, session, topic, subq, label):
    sort_value = getattr(subq.c, label)
    return model_query(context, models.Service,
                       func.coalesce(sort_value, 0),
                       session=session, read_deleted="no").\
        filter_by(topic=topic).\
        filter_by(disabled=False).\
        outerjoin((subq, models.Service.host == subq.c.host)).\
        order_by(sort_value).\
        all()


@require_admin_context
def service_get_all_volume_sorted(context):
    session = get_session()
    with session.begin():
        topic = CONF.volume_topic
        label = 'volume_gigabytes'
        subq = model_query(context, models.Volume.host,
                           func.sum(models.Volume.size).label(label),
                           session=session, read_deleted="no").\
            group_by(models.Volume.host).\
            subquery()
        return _service_get_all_topic_subquery(context,
                                               session,
                                               topic,
                                               subq,
                                               label)


@require_admin_context
def service_get_by_args(context, host, binary):
    result = model_query(context, models.Service).\
        filter_by(host=host).\
        filter_by(binary=binary).\
        first()

    if not result:
        raise exception.HostBinaryNotFound(host=host, binary=binary)

    return result


@require_admin_context
def service_create(context, values):
    service_ref = models.Service()
    service_ref.update(values)
    if not CONF.enable_new_services:
        service_ref.disabled = True
    service_ref.save()
    return service_ref


@require_admin_context
def service_update(context, service_id, values):
    session = get_session()
    with session.begin():
        service_ref = _service_get(context, service_id, session=session)
        service_ref.update(values)
        service_ref.save(session=session)


###################


def _metadata_refs(metadata_dict, meta_class):
    metadata_refs = []
    if metadata_dict:
        for k, v in metadata_dict.iteritems():
            metadata_ref = meta_class()
            metadata_ref['key'] = k
            metadata_ref['value'] = v
            metadata_refs.append(metadata_ref)
    return metadata_refs


def _dict_with_extra_specs(inst_type_query):
    """Convert type query result to dict with extra_spec and rate_limit.

    Takes a volume type query returned by sqlalchemy and returns it
    as a dictionary, converting the extra_specs entry from a list
    of dicts:

    'extra_specs' : [{'key': 'k1', 'value': 'v1', ...}, ...]
    to a single dict:
    'extra_specs' : {'k1': 'v1'}
    """
    inst_type_dict = dict(inst_type_query)
    extra_specs = dict([(x['key'], x['value'])
                        for x in inst_type_query['extra_specs']])
    inst_type_dict['extra_specs'] = extra_specs
    return inst_type_dict


###################


@require_admin_context
def iscsi_target_count_by_host(context, host):
    return model_query(context, models.IscsiTarget).\
        filter_by(host=host).\
        count()


@require_admin_context
def iscsi_target_create_safe(context, values):
    iscsi_target_ref = models.IscsiTarget()

    for (key, value) in values.iteritems():
        iscsi_target_ref[key] = value
    try:
        iscsi_target_ref.save()
        return iscsi_target_ref
    except IntegrityError:
        return None


###################


@require_context
def _quota_get(context, project_id, resource, session=None):
    result = model_query(context, models.Quota, session=session,
                         read_deleted="no").\
        filter_by(project_id=project_id).\
        filter_by(resource=resource).\
        first()

    if not result:
        raise exception.ProjectQuotaNotFound(project_id=project_id)

    return result


@require_context
def quota_get(context, project_id, resource):
    return _quota_get(context, project_id, resource)


@require_context
def quota_get_all_by_project(context, project_id):
    authorize_project_context(context, project_id)

    rows = model_query(context, models.Quota, read_deleted="no").\
        filter_by(project_id=project_id).\
        all()

    result = {'project_id': project_id}
    for row in rows:
        result[row.resource] = row.hard_limit

    return result


@require_admin_context
def quota_create(context, project_id, resource, limit):
    quota_ref = models.Quota()
    quota_ref.project_id = project_id
    quota_ref.resource = resource
    quota_ref.hard_limit = limit
    quota_ref.save()
    return quota_ref


@require_admin_context
def quota_update(context, project_id, resource, limit):
    session = get_session()
    with session.begin():
        quota_ref = _quota_get(context, project_id, resource, session=session)
        quota_ref.hard_limit = limit
        quota_ref.save(session=session)


@require_admin_context
def quota_destroy(context, project_id, resource):
    session = get_session()
    with session.begin():
        quota_ref = _quota_get(context, project_id, resource, session=session)
        quota_ref.delete(session=session)


###################


@require_context
def _quota_class_get(context, class_name, resource, session=None):
    result = model_query(context, models.QuotaClass, session=session,
                         read_deleted="no").\
        filter_by(class_name=class_name).\
        filter_by(resource=resource).\
        first()

    if not result:
        raise exception.QuotaClassNotFound(class_name=class_name)

    return result


@require_context
def quota_class_get(context, class_name, resource):
    return _quota_class_get(context, class_name, resource)


def quota_class_get_default(context):
    rows = model_query(context, models.QuotaClass,
                       read_deleted="no").\
        filter_by(class_name=_DEFAULT_QUOTA_NAME).all()

    result = {'class_name': _DEFAULT_QUOTA_NAME}
    for row in rows:
        result[row.resource] = row.hard_limit

    return result


@require_context
def quota_class_get_all_by_name(context, class_name):
    authorize_quota_class_context(context, class_name)

    rows = model_query(context, models.QuotaClass, read_deleted="no").\
        filter_by(class_name=class_name).\
        all()

    result = {'class_name': class_name}
    for row in rows:
        result[row.resource] = row.hard_limit

    return result


@require_admin_context
def quota_class_create(context, class_name, resource, limit):
    quota_class_ref = models.QuotaClass()
    quota_class_ref.class_name = class_name
    quota_class_ref.resource = resource
    quota_class_ref.hard_limit = limit
    quota_class_ref.save()
    return quota_class_ref


@require_admin_context
def quota_class_update(context, class_name, resource, limit):
    session = get_session()
    with session.begin():
        quota_class_ref = _quota_class_get(context, class_name, resource,
                                           session=session)
        quota_class_ref.hard_limit = limit
        quota_class_ref.save(session=session)


@require_admin_context
def quota_class_destroy(context, class_name, resource):
    session = get_session()
    with session.begin():
        quota_class_ref = _quota_class_get(context, class_name, resource,
                                           session=session)
        quota_class_ref.delete(session=session)


@require_admin_context
def quota_class_destroy_all_by_name(context, class_name):
    session = get_session()
    with session.begin():
        quota_classes = model_query(context, models.QuotaClass,
                                    session=session, read_deleted="no").\
            filter_by(class_name=class_name).\
            all()

        for quota_class_ref in quota_classes:
            quota_class_ref.delete(session=session)


###################


@require_context
def quota_usage_get(context, project_id, resource):
    result = model_query(context, models.QuotaUsage, read_deleted="no").\
        filter_by(project_id=project_id).\
        filter_by(resource=resource).\
        first()

    if not result:
        raise exception.QuotaUsageNotFound(project_id=project_id)

    return result


@require_context
def quota_usage_get_all_by_project(context, project_id):
    authorize_project_context(context, project_id)

    rows = model_query(context, models.QuotaUsage, read_deleted="no").\
        filter_by(project_id=project_id).\
        all()

    result = {'project_id': project_id}
    for row in rows:
        result[row.resource] = dict(in_use=row.in_use, reserved=row.reserved)

    return result


@require_admin_context
def _quota_usage_create(context, project_id, resource, in_use, reserved,
                        until_refresh, session=None):

    quota_usage_ref = models.QuotaUsage()
    quota_usage_ref.project_id = project_id
    quota_usage_ref.resource = resource
    quota_usage_ref.in_use = in_use
    quota_usage_ref.reserved = reserved
    quota_usage_ref.until_refresh = until_refresh
    quota_usage_ref.save(session=session)

    return quota_usage_ref


###################


@require_context
def _reservation_get(context, uuid, session=None):
    result = model_query(context, models.Reservation, session=session,
                         read_deleted="no").\
        filter_by(uuid=uuid).first()

    if not result:
        raise exception.ReservationNotFound(uuid=uuid)

    return result


@require_context
def reservation_get(context, uuid):
    return _reservation_get(context, uuid)


@require_context
def reservation_get_all_by_project(context, project_id):
    authorize_project_context(context, project_id)

    rows = model_query(context, models.Reservation, read_deleted="no").\
        filter_by(project_id=project_id).all()

    result = {'project_id': project_id}
    for row in rows:
        result.setdefault(row.resource, {})
        result[row.resource][row.uuid] = row.delta

    return result


@require_admin_context
def _reservation_create(context, uuid, usage, project_id, resource, delta,
                        expire, session=None):
    reservation_ref = models.Reservation()
    reservation_ref.uuid = uuid
    reservation_ref.usage_id = usage['id']
    reservation_ref.project_id = project_id
    reservation_ref.resource = resource
    reservation_ref.delta = delta
    reservation_ref.expire = expire
    reservation_ref.save(session=session)
    return reservation_ref


@require_admin_context
def reservation_create(context, uuid, usage, project_id, resource, delta,
                       expire):
    return _reservation_create(context, uuid, usage, project_id, resource,
                               delta, expire)


@require_admin_context
def reservation_destroy(context, uuid):
    session = get_session()
    with session.begin():
        reservation_ref = _reservation_get(context, uuid, session=session)
        reservation_ref.delete(session=session)


###################


# NOTE(johannes): The quota code uses SQL locking to ensure races don't
# cause under or over counting of resources. To avoid deadlocks, this
# code always acquires the lock on quota_usages before acquiring the lock
# on reservations.

def _get_quota_usages(context, session, project_id):
    # Broken out for testability
    rows = model_query(context, models.QuotaUsage,
                       read_deleted="no",
                       session=session).\
        filter_by(project_id=project_id).\
        with_lockmode('update').\
        all()
    return dict((row.resource, row) for row in rows)


@require_context
def quota_reserve(context, resources, quotas, deltas, expire,
                  until_refresh, max_age, project_id=None):
    elevated = context.elevated()
    session = get_session()
    with session.begin():
        if project_id is None:
            project_id = context.project_id

        # Get the current usages
        usages = _get_quota_usages(context, session, project_id)

        # Handle usage refresh
        work = set(deltas.keys())
        while work:
            resource = work.pop()

            # Do we need to refresh the usage?
            refresh = False
            if resource not in usages:
                usages[resource] = _quota_usage_create(elevated,
                                                       project_id,
                                                       resource,
                                                       0, 0,
                                                       until_refresh or None,
                                                       session=session)
                refresh = True
            elif usages[resource].in_use < 0:
                # Negative in_use count indicates a desync, so try to
                # heal from that...
                refresh = True
            elif usages[resource].until_refresh is not None:
                usages[resource].until_refresh -= 1
                if usages[resource].until_refresh <= 0:
                    refresh = True
            elif max_age and usages[resource].updated_at is not None and (
                (usages[resource].updated_at -
                    timeutils.utcnow()).seconds >= max_age):
                refresh = True

            # OK, refresh the usage
            if refresh:
                # Grab the sync routine
                sync = QUOTA_SYNC_FUNCTIONS[resources[resource].sync]
                volume_type_id = getattr(resources[resource],
                                         'volume_type_id', None)
                volume_type_name = getattr(resources[resource],
                                           'volume_type_name', None)
                updates = sync(elevated, project_id,
                               volume_type_id=volume_type_id,
                               volume_type_name=volume_type_name,
                               session=session)
                for res, in_use in updates.items():
                    # Make sure we have a destination for the usage!
                    if res not in usages:
                        usages[res] = _quota_usage_create(
                            elevated,
                            project_id,
                            res,
                            0, 0,
                            until_refresh or None,
                            session=session
                        )

                    # Update the usage
                    usages[res].in_use = in_use
                    usages[res].until_refresh = until_refresh or None

                    # Because more than one resource may be refreshed
                    # by the call to the sync routine, and we don't
                    # want to double-sync, we make sure all refreshed
                    # resources are dropped from the work set.
                    work.discard(res)

                    # NOTE(Vek): We make the assumption that the sync
                    #            routine actually refreshes the
                    #            resources that it is the sync routine
                    #            for.  We don't check, because this is
                    #            a best-effort mechanism.

        # Check for deltas that would go negative
        unders = [r for r, delta in deltas.items()
                  if delta < 0 and delta + usages[r].in_use < 0]

        # Now, let's check the quotas
        # NOTE(Vek): We're only concerned about positive increments.
        #            If a project has gone over quota, we want them to
        #            be able to reduce their usage without any
        #            problems.
        overs = [r for r, delta in deltas.items()
                 if quotas[r] >= 0 and delta >= 0 and
                 quotas[r] < delta + usages[r].total]

        # NOTE(Vek): The quota check needs to be in the transaction,
        #            but the transaction doesn't fail just because
        #            we're over quota, so the OverQuota raise is
        #            outside the transaction.  If we did the raise
        #            here, our usage updates would be discarded, but
        #            they're not invalidated by being over-quota.

        # Create the reservations
        if not overs:
            reservations = []
            for resource, delta in deltas.items():
                reservation = _reservation_create(elevated,
                                                  str(uuid.uuid4()),
                                                  usages[resource],
                                                  project_id,
                                                  resource, delta, expire,
                                                  session=session)
                reservations.append(reservation.uuid)

                # Also update the reserved quantity
                # NOTE(Vek): Again, we are only concerned here about
                #            positive increments.  Here, though, we're
                #            worried about the following scenario:
                #
                #            1) User initiates resize down.
                #            2) User allocates a new instance.
                #            3) Resize down fails or is reverted.
                #            4) User is now over quota.
                #
                #            To prevent this, we only update the
                #            reserved value if the delta is positive.
                if delta > 0:
                    usages[resource].reserved += delta

        # Apply updates to the usages table
        for usage_ref in usages.values():
            usage_ref.save(session=session)

    if unders:
        LOG.warning(_("Change will make usage less than 0 for the following "
                      "resources: %s") % unders)
    if overs:
        usages = dict((k, dict(in_use=v['in_use'], reserved=v['reserved']))
                      for k, v in usages.items())
        raise exception.OverQuota(overs=sorted(overs), quotas=quotas,
                                  usages=usages)

    return reservations


def _quota_reservations(session, context, reservations):
    """Return the relevant reservations."""

    # Get the listed reservations
    return model_query(context, models.Reservation,
                       read_deleted="no",
                       session=session).\
        filter(models.Reservation.uuid.in_(reservations)).\
        with_lockmode('update').\
        all()


@require_context
def reservation_commit(context, reservations, project_id=None):
    session = get_session()
    with session.begin():
        usages = _get_quota_usages(context, session, project_id)

        for reservation in _quota_reservations(session, context, reservations):
            usage = usages[reservation.resource]
            if reservation.delta >= 0:
                usage.reserved -= reservation.delta
            usage.in_use += reservation.delta

            reservation.delete(session=session)

        for usage in usages.values():
            usage.save(session=session)


@require_context
def reservation_rollback(context, reservations, project_id=None):
    session = get_session()
    with session.begin():
        usages = _get_quota_usages(context, session, project_id)

        for reservation in _quota_reservations(session, context, reservations):
            usage = usages[reservation.resource]
            if reservation.delta >= 0:
                usage.reserved -= reservation.delta

            reservation.delete(session=session)

        for usage in usages.values():
            usage.save(session=session)


@require_admin_context
def quota_destroy_all_by_project(context, project_id):
    session = get_session()
    with session.begin():
        quotas = model_query(context, models.Quota, session=session,
                             read_deleted="no").\
            filter_by(project_id=project_id).\
            all()

        for quota_ref in quotas:
            quota_ref.delete(session=session)

        quota_usages = model_query(context, models.QuotaUsage,
                                   session=session, read_deleted="no").\
            filter_by(project_id=project_id).\
            all()

        for quota_usage_ref in quota_usages:
            quota_usage_ref.delete(session=session)

        reservations = model_query(context, models.Reservation,
                                   session=session, read_deleted="no").\
            filter_by(project_id=project_id).\
            all()

        for reservation_ref in reservations:
            reservation_ref.delete(session=session)


@require_admin_context
def reservation_expire(context):
    session = get_session()
    with session.begin():
        current_time = timeutils.utcnow()
        results = model_query(context, models.Reservation, session=session,
                              read_deleted="no").\
            filter(models.Reservation.expire < current_time).\
            all()

        if results:
            for reservation in results:
                if reservation.delta >= 0:
                    reservation.usage.reserved -= reservation.delta
                    reservation.usage.save(session=session)

                reservation.delete(session=session)


###################


@require_admin_context
def volume_allocate_iscsi_target(context, volume_id, host):
    session = get_session()
    with session.begin():
        iscsi_target_ref = model_query(context, models.IscsiTarget,
                                       session=session, read_deleted="no").\
            filter_by(volume=None).\
            filter_by(host=host).\
            with_lockmode('update').\
            first()

        # NOTE(vish): if with_lockmode isn't supported, as in sqlite,
        #             then this has concurrency issues
        if not iscsi_target_ref:
            raise exception.NoMoreTargets()

        iscsi_target_ref.volume_id = volume_id
        session.add(iscsi_target_ref)

    return iscsi_target_ref.target_num


@require_admin_context
def volume_attached(context, volume_id, instance_uuid, host_name, mountpoint):
    if instance_uuid and not uuidutils.is_uuid_like(instance_uuid):
        raise exception.InvalidUUID(uuid=instance_uuid)

    session = get_session()
    with session.begin():
        volume_ref = _volume_get(context, volume_id, session=session)
        volume_ref['status'] = 'in-use'
        volume_ref['mountpoint'] = mountpoint
        volume_ref['attach_status'] = 'attached'
        volume_ref['instance_uuid'] = instance_uuid
        volume_ref['attached_host'] = host_name
        volume_ref.save(session=session)
        return volume_ref


@require_context
def volume_create(context, values):
    values['volume_metadata'] = _metadata_refs(values.get('metadata'),
                                               models.VolumeMetadata)
    if is_admin_context(context):
        values['volume_admin_metadata'] = \
            _metadata_refs(values.get('admin_metadata'),
                           models.VolumeAdminMetadata)
    elif values.get('volume_admin_metadata'):
        del values['volume_admin_metadata']

    volume_ref = models.Volume()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())
    volume_ref.update(values)

    session = get_session()
    with session.begin():
        volume_ref.save(session=session)

        return _volume_get(context, values['id'], session=session)


@require_admin_context
def volume_data_get_for_host(context, host):
    result = model_query(context,
                         func.count(models.Volume.id),
                         func.sum(models.Volume.size),
                         read_deleted="no").\
        filter_by(host=host).\
        first()

    # NOTE(vish): convert None to 0
    return (result[0] or 0, result[1] or 0)


@require_admin_context
def _volume_data_get_for_project(context, project_id, volume_type_id=None,
                                 session=None):
    query = model_query(context,
                        func.count(models.Volume.id),
                        func.sum(models.Volume.size),
                        read_deleted="no",
                        session=session).\
        filter_by(project_id=project_id)

    if volume_type_id:
        query = query.filter_by(volume_type_id=volume_type_id)

    result = query.first()

    # NOTE(vish): convert None to 0
    return (result[0] or 0, result[1] or 0)


@require_admin_context
def volume_data_get_for_project(context, project_id, volume_type_id=None):
    return _volume_data_get_for_project(context, project_id, volume_type_id)


@require_admin_context
def finish_volume_migration(context, src_vol_id, dest_vol_id):
    """Copy almost all columns from dest to source."""
    session = get_session()
    with session.begin():
        src_volume_ref = _volume_get(context, src_vol_id, session=session)
        dest_volume_ref = _volume_get(context, dest_vol_id, session=session)

        # NOTE(rpodolyaka): we should copy only column values, while model
        #                   instances also have relationships attributes, which
        #                   should be ignored
        def is_column(inst, attr):
            return attr in inst.__class__.__table__.columns

        for key, value in dest_volume_ref.iteritems():
            if key == 'id' or not is_column(dest_volume_ref, key):
                continue
            elif key == 'migration_status':
                value = None
            elif key == '_name_id':
                value = dest_volume_ref['_name_id'] or dest_volume_ref['id']

            setattr(src_volume_ref, key, value)


@require_admin_context
def volume_destroy(context, volume_id):
    session = get_session()
    now = timeutils.utcnow()
    with session.begin():
        model_query(context, models.Volume, session=session).\
            filter_by(id=volume_id).\
            update({'status': 'deleted',
                    'deleted': True,
                    'deleted_at': now,
                    'updated_at': literal_column('updated_at')})
        model_query(context, models.IscsiTarget, session=session).\
            filter_by(volume_id=volume_id).\
            update({'volume_id': None})
        model_query(context, models.VolumeMetadata, session=session).\
            filter_by(volume_id=volume_id).\
            update({'deleted': True,
                    'deleted_at': now,
                    'updated_at': literal_column('updated_at')})
        model_query(context, models.VolumeAdminMetadata, session=session).\
            filter_by(volume_id=volume_id).\
            update({'deleted': True,
                    'deleted_at': now,
                    'updated_at': literal_column('updated_at')})
        model_query(context, models.Transfer, session=session).\
            filter_by(volume_id=volume_id).\
            update({'deleted': True,
                    'deleted_at': now,
                    'updated_at': literal_column('updated_at')})


@require_admin_context
def volume_detached(context, volume_id):
    session = get_session()
    with session.begin():
        volume_ref = _volume_get(context, volume_id, session=session)
        # Hide status update from user if we're performing a volume migration
        if not volume_ref['migration_status']:
            volume_ref['status'] = 'available'
        volume_ref['mountpoint'] = None
        volume_ref['attach_status'] = 'detached'
        volume_ref['instance_uuid'] = None
        volume_ref['attached_host'] = None
        volume_ref['attach_time'] = None
        volume_ref.save(session=session)


@require_context
def _volume_get_query(context, session=None, project_only=False):
    if is_admin_context(context):
        return model_query(context, models.Volume, session=session,
                           project_only=project_only).\
            options(joinedload('volume_metadata')).\
            options(joinedload('volume_admin_metadata')).\
            options(joinedload('volume_type'))
    else:
        return model_query(context, models.Volume, session=session,
                           project_only=project_only).\
            options(joinedload('volume_metadata')).\
            options(joinedload('volume_type'))


@require_context
def _volume_get(context, volume_id, session=None):
    result = _volume_get_query(context, session=session, project_only=True).\
        filter_by(id=volume_id).\
        first()

    if not result:
        raise exception.VolumeNotFound(volume_id=volume_id)

    return result


@require_context
def volume_get(context, volume_id):
    return _volume_get(context, volume_id)


@require_admin_context
def volume_get_all(context, marker, limit, sort_key, sort_dir,
                   filters=None):
    """Retrieves all volumes.

    :param context: context to query under
    :param marker: the last item of the previous page, used to determine the
                   next page of results to return
    :param limit: maximum number of items to return
    :param sort_key: single attributes by which results should be sorted
    :param sort_dir: direction in which results should be sorted (asc, desc)
    :param filters: Filters for the query. A filter key/value of
                    'no_migration_targets'=True causes volumes with either
                    a NULL 'migration_status' or a 'migration_status' that
                    does not start with 'target:' to be retrieved.
    :returns: list of matching volumes
    """
    session = get_session()
    with session.begin():
        # Generate the query
        query = _generate_paginate_query(context, session, marker, limit,
                                         sort_key, sort_dir, filters)
        # No volumes would match, return empty list
        if query == None:
            return []
        return query.all()


@require_admin_context
def volume_get_all_by_host(context, host):
    return _volume_get_query(context).filter_by(host=host).all()


@require_admin_context
def volume_get_all_by_instance_uuid(context, instance_uuid):
    result = model_query(context, models.Volume, read_deleted="no").\
        options(joinedload('volume_metadata')).\
        options(joinedload('volume_admin_metadata')).\
        options(joinedload('volume_type')).\
        filter_by(instance_uuid=instance_uuid).\
        all()

    if not result:
        return []

    return result


@require_context
def volume_get_all_by_project(context, project_id, marker, limit, sort_key,
                              sort_dir, filters=None):
    """"Retrieves all volumes in a project.

    :param context: context to query under
    :param project_id: project for all volumes being retrieved
    :param marker: the last item of the previous page, used to determine the
                   next page of results to return
    :param limit: maximum number of items to return
    :param sort_key: single attributes by which results should be sorted
    :param sort_dir: direction in which results should be sorted (asc, desc)
    :param filters: Filters for the query. A filter key/value of
                    'no_migration_targets'=True causes volumes with either
                    a NULL 'migration_status' or a 'migration_status' that
                    does not start with 'target:' to be retrieved.
    :returns: list of matching volumes
    """
    session = get_session()
    with session.begin():
        authorize_project_context(context, project_id)
        # Add in the project filter without modifying the given filters
        filters = filters.copy() if filters else {}
        filters['project_id'] = project_id
        # Generate the query
        query = _generate_paginate_query(context, session, marker, limit,
                                         sort_key, sort_dir, filters)
        # No volumes would match, return empty list
        if query == None:
            return []
        return query.all()


def _generate_paginate_query(context, session, marker, limit, sort_key,
                             sort_dir, filters):
    """Generate the query to include the filters and the paginate options.

    Returns a query with sorting / pagination criteria added or None
    if the given filters will not yield any results.

    :param context: context to query under
    :param session: the session to use
    :param marker: the last item of the previous page; we returns the next
                    results after this value.
    :param limit: maximum number of items to return
    :param sort_key: single attributes by which results should be sorted
    :param sort_dir: direction in which results should be sorted (asc, desc)
    :param filters: dictionary of filters; values that are lists,
                    tuples, sets, or frozensets cause an 'IN' test to
                    be performed, while exact matching ('==' operator)
                    is used for other values
    :returns: updated query or None
    """
    query = _volume_get_query(context, session=session)

    if filters:
        filters = filters.copy()

        # 'no_migration_targets' is unique, must be either NULL or
        # not start with 'target:'
        if ('no_migration_targets' in filters and
                filters['no_migration_targets'] == True):
            filters.pop('no_migration_targets')
            try:
                column_attr = getattr(models.Volume, 'migration_status')
                conditions = [column_attr == None,
                              column_attr.op('NOT LIKE')('target:%')]
                query = query.filter(or_(*conditions))
            except AttributeError:
                log_msg = _("'migration_status' column could not be found.")
                LOG.debug(log_msg)
                return None

        # Apply exact match filters for everything else, ensure that the
        # filter value exists on the model
        for key in filters.keys():
            # metadata is unique, must be a dict
            if key == 'metadata':
                if not isinstance(filters[key], dict):
                    log_msg = _("'metadata' filter value is not valid.")
                    LOG.debug(log_msg)
                    return None
                continue
            try:
                column_attr = getattr(models.Volume, key)
                # Do not allow relationship properties since those require
                # schema specific knowledge
                prop = getattr(column_attr, 'property')
                if isinstance(prop, RelationshipProperty):
                    log_msg = (_("'%s' filter key is not valid, "
                                 "it maps to a relationship.")) % key
                    LOG.debug(log_msg)
                    return None
            except AttributeError:
                log_msg = _("'%s' filter key is not valid.") % key
                LOG.debug(log_msg)
                return None

        # Holds the simple exact matches
        filter_dict = {}

        # Iterate over all filters, special case the filter is necessary
        for key, value in filters.iteritems():
            if key == 'metadata':
                # model.VolumeMetadata defines the backref to Volumes as
                # 'volume_metadata', use that column attribute key
                key = 'volume_metadata'
                column_attr = getattr(models.Volume, key)
                for k, v in value.iteritems():
                    query = query.filter(column_attr.any(key=k, value=v))
            elif isinstance(value, (list, tuple, set, frozenset)):
                # Looking for values in a list; apply to query directly
                column_attr = getattr(models.Volume, key)
                query = query.filter(column_attr.in_(value))
            else:
                # OK, simple exact match; save for later
                filter_dict[key] = value

        # Apply simple exact matches
        if filter_dict:
            query = query.filter_by(**filter_dict)

    marker_volume = None
    if marker is not None:
        marker_volume = _volume_get(context, marker, session)

    return sqlalchemyutils.paginate_query(query, models.Volume, limit,
                                          [sort_key, 'created_at', 'id'],
                                          marker=marker_volume,
                                          sort_dir=sort_dir)


@require_admin_context
def volume_get_iscsi_target_num(context, volume_id):
    result = model_query(context, models.IscsiTarget, read_deleted="yes").\
        filter_by(volume_id=volume_id).\
        first()

    if not result:
        raise exception.ISCSITargetNotFoundForVolume(volume_id=volume_id)

    return result.target_num


@require_context
def volume_update(context, volume_id, values):
    session = get_session()
    with session.begin():
        metadata = values.get('metadata')
        if metadata is not None:
            _volume_user_metadata_update(context,
                                         volume_id,
                                         values.pop('metadata'),
                                         delete=True,
                                         session=session)

        admin_metadata = values.get('admin_metadata')
        if is_admin_context(context) and admin_metadata is not None:
            _volume_admin_metadata_update(context,
                                          volume_id,
                                          values.pop('admin_metadata'),
                                          delete=True,
                                          session=session)

        volume_ref = _volume_get(context, volume_id, session=session)
        volume_ref.update(values)
        volume_ref.save(session=session)
        return volume_ref


####################

def _volume_x_metadata_get_query(context, volume_id, model, session=None):
    return model_query(context, model, session=session, read_deleted="no").\
        filter_by(volume_id=volume_id)


def _volume_x_metadata_get(context, volume_id, model, session=None):
    rows = _volume_x_metadata_get_query(context, volume_id, model,
                                        session=session).all()
    result = {}
    for row in rows:
        result[row['key']] = row['value']

    return result


def _volume_x_metadata_get_item(context, volume_id, key, model, notfound_exec,
                                session=None):
    result = _volume_x_metadata_get_query(context, volume_id,
                                          model, session=session).\
        filter_by(key=key).\
        first()

    if not result:
        raise notfound_exec(metadata_key=key, volume_id=volume_id)
    return result


def _volume_x_metadata_update(context, volume_id, metadata, delete,
                              model, notfound_exec, session=None):
    if not session:
        session = get_session()

    with session.begin(subtransactions=True):
        # Set existing metadata to deleted if delete argument is True
        if delete:
            original_metadata = _volume_x_metadata_get(context, volume_id,
                                                       model, session=session)
            for meta_key, meta_value in original_metadata.iteritems():
                if meta_key not in metadata:
                    meta_ref = _volume_x_metadata_get_item(context, volume_id,
                                                           meta_key, model,
                                                           notfound_exec,
                                                           session=session)
                    meta_ref.update({'deleted': True})
                    meta_ref.save(session=session)

        meta_ref = None

        # Now update all existing items with new values, or create new meta
        # objects
        for meta_key, meta_value in metadata.items():

            # update the value whether it exists or not
            item = {"value": meta_value}

            try:
                meta_ref = _volume_x_metadata_get_item(context, volume_id,
                                                       meta_key, model,
                                                       notfound_exec,
                                                       session=session)
            except notfound_exec:
                meta_ref = model()
                item.update({"key": meta_key, "volume_id": volume_id})

            meta_ref.update(item)
            meta_ref.save(session=session)

    return _volume_x_metadata_get(context, volume_id, model)


def _volume_user_metadata_get_query(context, volume_id, session=None):
    return _volume_x_metadata_get_query(context, volume_id,
                                        models.VolumeMetadata, session=session)


@require_context
@require_volume_exists
def _volume_user_metadata_get(context, volume_id, session=None):
    return _volume_x_metadata_get(context, volume_id,
                                  models.VolumeMetadata, session=session)


@require_context
def _volume_user_metadata_get_item(context, volume_id, key, session=None):
    return _volume_x_metadata_get_item(context, volume_id, key,
                                       models.VolumeMetadata,
                                       exception.VolumeMetadataNotFound,
                                       session=session)


@require_context
@require_volume_exists
def _volume_user_metadata_update(context, volume_id, metadata, delete,
                                 session=None):
    return _volume_x_metadata_update(context, volume_id, metadata, delete,
                                     models.VolumeMetadata,
                                     exception.VolumeMetadataNotFound,
                                     session=session)


@require_context
@require_volume_exists
def volume_metadata_get_item(context, volume_id, key):
    return _volume_user_metadata_get_item(context, volume_id, key)


@require_context
@require_volume_exists
def volume_metadata_get(context, volume_id):
    return _volume_user_metadata_get(context, volume_id)


@require_context
@require_volume_exists
def volume_metadata_delete(context, volume_id, key):
    _volume_user_metadata_get_query(context, volume_id).\
        filter_by(key=key).\
        update({'deleted': True,
                'deleted_at': timeutils.utcnow(),
                'updated_at': literal_column('updated_at')})


@require_context
@require_volume_exists
def volume_metadata_update(context, volume_id, metadata, delete):
    return _volume_user_metadata_update(context, volume_id, metadata, delete)


###################


def _volume_admin_metadata_get_query(context, volume_id, session=None):
    return _volume_x_metadata_get_query(context, volume_id,
                                        models.VolumeAdminMetadata,
                                        session=session)


@require_admin_context
@require_volume_exists
def _volume_admin_metadata_get(context, volume_id, session=None):
    return _volume_x_metadata_get(context, volume_id,
                                  models.VolumeAdminMetadata, session=session)


@require_admin_context
@require_volume_exists
def _volume_admin_metadata_update(context, volume_id, metadata, delete,
                                  session=None):
    return _volume_x_metadata_update(context, volume_id, metadata, delete,
                                     models.VolumeAdminMetadata,
                                     exception.VolumeAdminMetadataNotFound,
                                     session=session)


@require_admin_context
@require_volume_exists
def volume_admin_metadata_get(context, volume_id):
    return _volume_admin_metadata_get(context, volume_id)


@require_admin_context
@require_volume_exists
def volume_admin_metadata_delete(context, volume_id, key):
    _volume_admin_metadata_get_query(context, volume_id).\
        filter_by(key=key).\
        update({'deleted': True,
                'deleted_at': timeutils.utcnow(),
                'updated_at': literal_column('updated_at')})


@require_admin_context
@require_volume_exists
def volume_admin_metadata_update(context, volume_id, metadata, delete):
    return _volume_admin_metadata_update(context, volume_id, metadata, delete)


###################


@require_context
def snapshot_create(context, values):
    values['snapshot_metadata'] = _metadata_refs(values.get('metadata'),
                                                 models.SnapshotMetadata)
    snapshot_ref = models.Snapshot()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())
    snapshot_ref.update(values)

    session = get_session()
    with session.begin():
        snapshot_ref.save(session=session)

        return _snapshot_get(context, values['id'], session=session)


@require_admin_context
def snapshot_destroy(context, snapshot_id):
    session = get_session()
    with session.begin():
        model_query(context, models.Snapshot, session=session).\
            filter_by(id=snapshot_id).\
            update({'status': 'deleted',
                    'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})
        model_query(context, models.SnapshotMetadata, session=session).\
            filter_by(snapshot_id=snapshot_id).\
            update({'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})


@require_context
def _snapshot_get(context, snapshot_id, session=None):
    result = model_query(context, models.Snapshot, session=session,
                         project_only=True).\
        options(joinedload('volume')).\
        options(joinedload('snapshot_metadata')).\
        filter_by(id=snapshot_id).\
        first()

    if not result:
        raise exception.SnapshotNotFound(snapshot_id=snapshot_id)

    return result


@require_context
def snapshot_get(context, snapshot_id):
    return _snapshot_get(context, snapshot_id)


@require_admin_context
def snapshot_get_all(context):
    return model_query(context, models.Snapshot).\
        options(joinedload('snapshot_metadata')).\
        all()


@require_context
def snapshot_get_all_for_volume(context, volume_id):
    return model_query(context, models.Snapshot, read_deleted='no',
                       project_only=True).\
        filter_by(volume_id=volume_id).\
        options(joinedload('snapshot_metadata')).\
        all()


@require_context
def snapshot_get_all_by_project(context, project_id):
    authorize_project_context(context, project_id)
    return model_query(context, models.Snapshot).\
        filter_by(project_id=project_id).\
        options(joinedload('snapshot_metadata')).\
        all()


@require_context
def _snapshot_data_get_for_project(context, project_id, volume_type_id=None,
                                   session=None):
    authorize_project_context(context, project_id)
    query = model_query(context,
                        func.count(models.Snapshot.id),
                        func.sum(models.Snapshot.volume_size),
                        read_deleted="no",
                        session=session).\
        filter_by(project_id=project_id)

    if volume_type_id:
        query = query.join('volume').filter_by(volume_type_id=volume_type_id)

    result = query.first()

    # NOTE(vish): convert None to 0
    return (result[0] or 0, result[1] or 0)


@require_context
def snapshot_data_get_for_project(context, project_id, volume_type_id=None):
    return _snapshot_data_get_for_project(context, project_id, volume_type_id)


@require_context
def snapshot_get_active_by_window(context, begin, end=None, project_id=None):
    """Return snapshots that were active during window."""

    query = model_query(context, models.Snapshot, read_deleted="yes")
    query = query.filter(or_(models.Snapshot.deleted_at == None,
                             models.Snapshot.deleted_at > begin))
    query = query.options(joinedload(models.Snapshot.volume))
    if end:
        query = query.filter(models.Snapshot.created_at < end)
    if project_id:
        query = query.filter_by(project_id=project_id)

    return query.all()


@require_context
def snapshot_update(context, snapshot_id, values):
    session = get_session()
    with session.begin():
        snapshot_ref = _snapshot_get(context, snapshot_id, session=session)
        snapshot_ref.update(values)
        snapshot_ref.save(session=session)

####################


def _snapshot_metadata_get_query(context, snapshot_id, session=None):
    return model_query(context, models.SnapshotMetadata,
                       session=session, read_deleted="no").\
        filter_by(snapshot_id=snapshot_id)


@require_context
@require_snapshot_exists
def _snapshot_metadata_get(context, snapshot_id, session=None):
    rows = _snapshot_metadata_get_query(context, snapshot_id, session).all()
    result = {}
    for row in rows:
        result[row['key']] = row['value']

    return result


@require_context
@require_snapshot_exists
def snapshot_metadata_get(context, snapshot_id):
    return _snapshot_metadata_get(context, snapshot_id)


@require_context
@require_snapshot_exists
def snapshot_metadata_delete(context, snapshot_id, key):
    _snapshot_metadata_get_query(context, snapshot_id).\
        filter_by(key=key).\
        update({'deleted': True,
                'deleted_at': timeutils.utcnow(),
                'updated_at': literal_column('updated_at')})


@require_context
def _snapshot_metadata_get_item(context, snapshot_id, key, session=None):
    result = _snapshot_metadata_get_query(context,
                                          snapshot_id,
                                          session=session).\
        filter_by(key=key).\
        first()

    if not result:
        raise exception.SnapshotMetadataNotFound(metadata_key=key,
                                                 snapshot_id=snapshot_id)
    return result


@require_context
@require_snapshot_exists
def snapshot_metadata_update(context, snapshot_id, metadata, delete):
    session = get_session()
    with session.begin():
        # Set existing metadata to deleted if delete argument is True
        if delete:
            original_metadata = _snapshot_metadata_get(context, snapshot_id,
                                                       session)
            for meta_key, meta_value in original_metadata.iteritems():
                if meta_key not in metadata:
                    meta_ref = _snapshot_metadata_get_item(context,
                                                           snapshot_id,
                                                           meta_key, session)
                    meta_ref.update({'deleted': True})
                    meta_ref.save(session=session)

        meta_ref = None

        # Now update all existing items with new values, or create new meta
        # objects
        for meta_key, meta_value in metadata.items():

            # update the value whether it exists or not
            item = {"value": meta_value}

            try:
                meta_ref = _snapshot_metadata_get_item(context, snapshot_id,
                                                       meta_key, session)
            except exception.SnapshotMetadataNotFound as e:
                meta_ref = models.SnapshotMetadata()
                item.update({"key": meta_key, "snapshot_id": snapshot_id})

            meta_ref.update(item)
            meta_ref.save(session=session)

    return snapshot_metadata_get(context, snapshot_id)

###################


@require_admin_context
def volume_type_create(context, values):
    """Create a new instance type.

    In order to pass in extra specs, the values dict should contain a
    'extra_specs' key/value pair:
    {'extra_specs' : {'k1': 'v1', 'k2': 'v2', ...}}
    """
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())

    session = get_session()
    with session.begin():
        try:
            _volume_type_get_by_name(context, values['name'], session)
            raise exception.VolumeTypeExists(id=values['name'])
        except exception.VolumeTypeNotFoundByName:
            pass
        try:
            _volume_type_get(context, values['id'], session)
            raise exception.VolumeTypeExists(id=values['id'])
        except exception.VolumeTypeNotFound:
            pass
        try:
            values['extra_specs'] = _metadata_refs(values.get('extra_specs'),
                                                   models.VolumeTypeExtraSpecs)
            volume_type_ref = models.VolumeTypes()
            volume_type_ref.update(values)
            volume_type_ref.save(session=session)
        except Exception as e:
            raise db_exc.DBError(e)
        return volume_type_ref


@require_context
def volume_type_get_all(context, inactive=False, filters=None):
    """Returns a dict describing all volume_types with name as key."""
    filters = filters or {}

    read_deleted = "yes" if inactive else "no"
    rows = model_query(context, models.VolumeTypes,
                       read_deleted=read_deleted).\
        options(joinedload('extra_specs')).\
        order_by("name").\
        all()

    result = {}
    for row in rows:
        result[row['name']] = _dict_with_extra_specs(row)

    return result


@require_context
def _volume_type_get(context, id, session=None, inactive=False):
    read_deleted = "yes" if inactive else "no"
    result = model_query(context,
                         models.VolumeTypes,
                         session=session,
                         read_deleted=read_deleted).\
        options(joinedload('extra_specs')).\
        filter_by(id=id).\
        first()

    if not result:
        raise exception.VolumeTypeNotFound(volume_type_id=id)

    return _dict_with_extra_specs(result)


@require_context
def volume_type_get(context, id, inactive=False):
    """Return a dict describing specific volume_type."""

    return _volume_type_get(context, id, None, inactive)


@require_context
def _volume_type_get_by_name(context, name, session=None):
    result = model_query(context, models.VolumeTypes, session=session).\
        options(joinedload('extra_specs')).\
        filter_by(name=name).\
        first()

    if not result:
        raise exception.VolumeTypeNotFoundByName(volume_type_name=name)
    else:
        return _dict_with_extra_specs(result)


@require_context
def volume_type_get_by_name(context, name):
    """Return a dict describing specific volume_type."""

    return _volume_type_get_by_name(context, name)


@require_admin_context
def volume_type_qos_associations_get(context, qos_specs_id, inactive=False):
    read_deleted = "yes" if inactive else "no"
    return model_query(context, models.VolumeTypes,
                       read_deleted=read_deleted). \
        filter_by(qos_specs_id=qos_specs_id).all()


@require_admin_context
def volume_type_qos_associate(context, type_id, qos_specs_id):
    session = get_session()
    with session.begin():
        _volume_type_get(context, type_id, session)

        session.query(models.VolumeTypes). \
            filter_by(id=type_id). \
            update({'qos_specs_id': qos_specs_id,
                    'updated_at': timeutils.utcnow()})


@require_admin_context
def volume_type_qos_disassociate(context, qos_specs_id, type_id):
    """Disassociate volume type from qos specs."""
    session = get_session()
    with session.begin():
        _volume_type_get(context, type_id, session)

        session.query(models.VolumeTypes). \
            filter_by(id=type_id). \
            filter_by(qos_specs_id=qos_specs_id). \
            update({'qos_specs_id': None,
                    'updated_at': timeutils.utcnow()})


@require_admin_context
def volume_type_qos_disassociate_all(context, qos_specs_id):
    """Disassociate all volume types associated with specified qos specs."""
    session = get_session()
    with session.begin():
        session.query(models.VolumeTypes). \
            filter_by(qos_specs_id=qos_specs_id). \
            update({'qos_specs_id': None,
                    'updated_at': timeutils.utcnow()})


@require_admin_context
def volume_type_qos_specs_get(context, type_id):
    """Return all qos specs for given volume type.

    result looks like:
        {
         'qos_specs':
                     {
                        'id': 'qos-specs-id',
                        'name': 'qos_specs_name',
                        'consumer': 'Consumer',
                        'specs': {
                            'key1': 'value1',
                            'key2': 'value2',
                            'key3': 'value3'
                        }
                     }
        }

    """
    session = get_session()
    with session.begin():
        _volume_type_get(context, type_id, session)

        row = session.query(models.VolumeTypes). \
            options(joinedload('qos_specs')). \
            filter_by(id=type_id). \
            first()

        # row.qos_specs is a list of QualityOfServiceSpecs ref
        specs = _dict_with_qos_specs(row.qos_specs)

        if not specs:
            # turn empty list to None
            specs = None
        else:
            specs = specs[0]

        return {'qos_specs': specs}


@require_admin_context
def volume_type_destroy(context, id):
    session = get_session()
    with session.begin():
        _volume_type_get(context, id, session)
        results = model_query(context, models.Volume, session=session). \
            filter_by(volume_type_id=id).all()
        if results:
            msg = _('VolumeType %s deletion failed, VolumeType in use.') % id
            LOG.error(msg)
            raise exception.VolumeTypeInUse(volume_type_id=id)
        model_query(context, models.VolumeTypes, session=session).\
            filter_by(id=id).\
            update({'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})
        model_query(context, models.VolumeTypeExtraSpecs, session=session).\
            filter_by(volume_type_id=id).\
            update({'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})


@require_context
def volume_get_active_by_window(context,
                                begin,
                                end=None,
                                project_id=None):
    """Return volumes that were active during window."""
    query = model_query(context, models.Volume, read_deleted="yes")
    query = query.filter(or_(models.Volume.deleted_at == None,
                             models.Volume.deleted_at > begin))
    if end:
        query = query.filter(models.Volume.created_at < end)
    if project_id:
        query = query.filter_by(project_id=project_id)

    return query.all()


####################


def _volume_type_extra_specs_query(context, volume_type_id, session=None):
    return model_query(context, models.VolumeTypeExtraSpecs, session=session,
                       read_deleted="no").\
        filter_by(volume_type_id=volume_type_id)


@require_context
def volume_type_extra_specs_get(context, volume_type_id):
    rows = _volume_type_extra_specs_query(context, volume_type_id).\
        all()

    result = {}
    for row in rows:
        result[row['key']] = row['value']

    return result


@require_context
def volume_type_extra_specs_delete(context, volume_type_id, key):
    session = get_session()
    with session.begin():
        _volume_type_extra_specs_get_item(context, volume_type_id, key,
                                          session)
        _volume_type_extra_specs_query(context, volume_type_id, session).\
            filter_by(key=key).\
            update({'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})


@require_context
def _volume_type_extra_specs_get_item(context, volume_type_id, key,
                                      session=None):
    result = _volume_type_extra_specs_query(
        context, volume_type_id, session=session).\
        filter_by(key=key).\
        first()

    if not result:
        raise exception.VolumeTypeExtraSpecsNotFound(
            extra_specs_key=key,
            volume_type_id=volume_type_id)

    return result


@require_context
def volume_type_extra_specs_update_or_create(context, volume_type_id,
                                             specs):
    session = get_session()
    with session.begin():
        spec_ref = None
        for key, value in specs.iteritems():
            try:
                spec_ref = _volume_type_extra_specs_get_item(
                    context, volume_type_id, key, session)
            except exception.VolumeTypeExtraSpecsNotFound as e:
                spec_ref = models.VolumeTypeExtraSpecs()
            spec_ref.update({"key": key, "value": value,
                             "volume_type_id": volume_type_id,
                             "deleted": False})
            spec_ref.save(session=session)

        return specs


####################


@require_admin_context
def qos_specs_create(context, values):
    """Create a new QoS specs.

    :param values dictionary that contains specifications for QoS
          e.g. {'name': 'Name',
                'qos_specs': {
                    'consumer': 'front-end',
                    'total_iops_sec': 1000,
                    'total_bytes_sec': 1024000
                    }
                }
    """
    specs_id = str(uuid.uuid4())

    session = get_session()
    with session.begin():
        try:
            _qos_specs_get_by_name(context, values['name'], session)
            raise exception.QoSSpecsExists(specs_id=values['name'])
        except exception.QoSSpecsNotFound:
            pass
        try:
            # Insert a root entry for QoS specs
            specs_root = models.QualityOfServiceSpecs()
            root = dict(id=specs_id)
            # 'QoS_Specs_Name' is a internal reserved key to store
            # the name of QoS specs
            root['key'] = 'QoS_Specs_Name'
            root['value'] = values['name']
            LOG.debug("DB qos_specs_create(): root %s", root)
            specs_root.update(root)
            specs_root.save(session=session)

            # Insert all specification entries for QoS specs
            for k, v in values['qos_specs'].iteritems():
                item = dict(key=k, value=v, specs_id=specs_id)
                item['id'] = str(uuid.uuid4())
                spec_entry = models.QualityOfServiceSpecs()
                spec_entry.update(item)
                spec_entry.save(session=session)
        except Exception as e:
            raise db_exc.DBError(e)

        return dict(id=specs_root.id, name=specs_root.value)


@require_admin_context
def _qos_specs_get_by_name(context, name, session=None, inactive=False):
    read_deleted = 'yes' if inactive else 'no'
    results = model_query(context, models.QualityOfServiceSpecs,
                          read_deleted=read_deleted, session=session). \
        filter_by(key='QoS_Specs_Name'). \
        filter_by(value=name). \
        options(joinedload('specs')).all()

    if not results:
        raise exception.QoSSpecsNotFound(specs_id=name)

    return results


@require_admin_context
def _qos_specs_get_ref(context, qos_specs_id, session=None, inactive=False):
    read_deleted = 'yes' if inactive else 'no'
    result = model_query(context, models.QualityOfServiceSpecs,
                         read_deleted=read_deleted, session=session). \
        filter_by(id=qos_specs_id). \
        options(joinedload_all('specs')).all()

    if not result:
        raise exception.QoSSpecsNotFound(specs_id=qos_specs_id)

    return result


def _dict_with_children_specs(specs):
    """Convert specs list to a dict."""
    result = {}
    for spec in specs:
        # Skip deleted keys
        if not spec['deleted']:
            result.update({spec['key']: spec['value']})

    return result


def _dict_with_qos_specs(rows):
    """Convert qos specs query results to list.

    Qos specs query results are a list of quality_of_service_specs refs,
    some are root entry of a qos specs (key == 'QoS_Specs_Name') and the
    rest are children entry, a.k.a detailed specs for a qos specs. This
    function converts query results to a dict using spec name as key.
    """
    result = []
    for row in rows:
        if row['key'] == 'QoS_Specs_Name':
            member = {}
            member['name'] = row['value']
            member.update(dict(id=row['id']))
            if row.specs:
                spec_dict = _dict_with_children_specs(row.specs)
                member.update(dict(consumer=spec_dict['consumer']))
                del spec_dict['consumer']
                member.update(dict(specs=spec_dict))
            result.append(member)
    return result


@require_admin_context
def qos_specs_get(context, qos_specs_id, inactive=False):
    rows = _qos_specs_get_ref(context, qos_specs_id, None, inactive)

    return _dict_with_qos_specs(rows)[0]


@require_admin_context
def qos_specs_get_all(context, inactive=False, filters=None):
    """Returns a list of all qos_specs.

    Results is like:
        [{
            'id': SPECS-UUID,
            'name': 'qos_spec-1',
            'consumer': 'back-end',
            'specs': {
                'key1': 'value1',
                'key2': 'value2',
                ...
            }
         },
         {
            'id': SPECS-UUID,
            'name': 'qos_spec-2',
            'consumer': 'front-end',
            'specs': {
                'key1': 'value1',
                'key2': 'value2',
                ...
            }
         },
        ]
    """
    filters = filters or {}
    #TODO(zhiteng) Add filters for 'consumer'

    read_deleted = "yes" if inactive else "no"
    rows = model_query(context, models.QualityOfServiceSpecs,
                       read_deleted=read_deleted). \
        options(joinedload_all('specs')).all()

    return _dict_with_qos_specs(rows)


@require_admin_context
def qos_specs_get_by_name(context, name, inactive=False):
    rows = _qos_specs_get_by_name(context, name, None, inactive)

    return _dict_with_qos_specs(rows)[0]


@require_admin_context
def qos_specs_associations_get(context, qos_specs_id):
    """Return all entities associated with specified qos specs.

    For now, the only entity that is possible to associate with
    a qos specs is volume type, so this is just a wrapper of
    volume_type_qos_associations_get(). But it's possible to
    extend qos specs association to other entities, such as volumes,
    sometime in future.
    """
    # Raise QoSSpecsNotFound if no specs found
    _qos_specs_get_ref(context, qos_specs_id, None)
    return volume_type_qos_associations_get(context, qos_specs_id)


@require_admin_context
def qos_specs_associate(context, qos_specs_id, type_id):
    """Associate volume type from specified qos specs."""
    return volume_type_qos_associate(context, type_id, qos_specs_id)


@require_admin_context
def qos_specs_disassociate(context, qos_specs_id, type_id):
    """Disassociate volume type from specified qos specs."""
    return volume_type_qos_disassociate(context, qos_specs_id, type_id)


@require_admin_context
def qos_specs_disassociate_all(context, qos_specs_id):
    """Disassociate all entities associated with specified qos specs.

    For now, the only entity that is possible to associate with
    a qos specs is volume type, so this is just a wrapper of
    volume_type_qos_disassociate_all(). But it's possible to
    extend qos specs association to other entities, such as volumes,
    sometime in future.
    """
    return volume_type_qos_disassociate_all(context, qos_specs_id)


@require_admin_context
def qos_specs_item_delete(context, qos_specs_id, key):
    session = get_session()
    with session.begin():
        _qos_specs_get_item(context, qos_specs_id, key)
        session.query(models.QualityOfServiceSpecs). \
            filter(models.QualityOfServiceSpecs.key == key). \
            filter(models.QualityOfServiceSpecs.specs_id == qos_specs_id). \
            update({'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})


@require_admin_context
def qos_specs_delete(context, qos_specs_id):
    session = get_session()
    with session.begin():
        _qos_specs_get_ref(context, qos_specs_id, session)
        session.query(models.QualityOfServiceSpecs).\
            filter(or_(models.QualityOfServiceSpecs.id == qos_specs_id,
                       models.QualityOfServiceSpecs.specs_id ==
                       qos_specs_id)).\
            update({'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})


@require_admin_context
def _qos_specs_get_item(context, qos_specs_id, key, session=None):
    result = model_query(context, models.QualityOfServiceSpecs,
                         session=session). \
        filter(models.QualityOfServiceSpecs.key == key). \
        filter(models.QualityOfServiceSpecs.specs_id == qos_specs_id). \
        first()

    if not result:
        raise exception.QoSSpecsKeyNotFound(
            specs_key=key,
            specs_id=qos_specs_id)

    return result


@require_admin_context
def qos_specs_update(context, qos_specs_id, specs):
    """Make updates to a existing qos specs.

    Perform add, update or delete key/values to a qos specs.
    """

    session = get_session()
    with session.begin():
        # make sure qos specs exists
        _qos_specs_get_ref(context, qos_specs_id, session)
        spec_ref = None
        for key in specs.keys():
            try:
                spec_ref = _qos_specs_get_item(
                    context, qos_specs_id, key, session)
            except exception.QoSSpecsKeyNotFound as e:
                spec_ref = models.QualityOfServiceSpecs()
            id = None
            if spec_ref.get('id', None):
                id = spec_ref['id']
            else:
                id = str(uuid.uuid4())
            value = dict(id=id, key=key, value=specs[key],
                         specs_id=qos_specs_id,
                         deleted=False)
            LOG.debug('qos_specs_update() value: %s' % value)
            spec_ref.update(value)
            spec_ref.save(session=session)

        return specs


####################


@require_context
def volume_type_encryption_get(context, volume_type_id, session=None):
    return model_query(context, models.Encryption, session=session,
                       read_deleted="no").\
        filter_by(volume_type_id=volume_type_id).first()


@require_admin_context
def volume_type_encryption_delete(context, volume_type_id):
    session = get_session()
    with session.begin():
        encryption = volume_type_encryption_get(context, volume_type_id,
                                                session)
        encryption.update({'deleted': True,
                           'deleted_at': timeutils.utcnow(),
                           'updated_at': literal_column('updated_at')})


@require_admin_context
def volume_type_encryption_create(context, volume_type_id, values):
    session = get_session()
    with session.begin():
        encryption = models.Encryption()

        if 'volume_type_id' not in values:
            values['volume_type_id'] = volume_type_id

        encryption.update(values)
        encryption.save(session=session)

        return encryption


@require_admin_context
def volume_type_encryption_update(context, volume_type_id, values):
    session = get_session()
    with session.begin():
        encryption = volume_type_encryption_get(context, volume_type_id,
                                                session)

        if not encryption:
            raise exception.VolumeTypeEncryptionNotFound(type_id=
                                                         volume_type_id)

        encryption.update(values)
        encryption.save(session=session)

        return encryption


def volume_type_encryption_volume_get(context, volume_type_id, session=None):
    volume_list = _volume_get_query(context, session=session,
                                    project_only=False).\
        filter_by(volume_type_id=volume_type_id).\
        all()
    return volume_list

####################


@require_context
def volume_encryption_metadata_get(context, volume_id, session=None):
    """Return the encryption key id for a given volume."""

    volume_ref = _volume_get(context, volume_id)
    encryption_ref = volume_type_encryption_get(context,
                                                volume_ref['volume_type_id'])

    return {
        'encryption_key_id': volume_ref['encryption_key_id'],
        'control_location': encryption_ref['control_location'],
        'cipher': encryption_ref['cipher'],
        'key_size': encryption_ref['key_size'],
        'provider': encryption_ref['provider'],
    }


####################


@require_context
def _volume_glance_metadata_get_all(context, session=None):
    rows = model_query(context,
                       models.VolumeGlanceMetadata,
                       project_only=True,
                       session=session).\
        filter_by(deleted=False).\
        all()

    return rows


@require_context
def volume_glance_metadata_get_all(context):
    """Return the Glance metadata for all volumes."""

    return _volume_glance_metadata_get_all(context)


@require_context
@require_volume_exists
def _volume_glance_metadata_get(context, volume_id, session=None):
    rows = model_query(context, models.VolumeGlanceMetadata, session=session).\
        filter_by(volume_id=volume_id).\
        filter_by(deleted=False).\
        all()

    if not rows:
        raise exception.GlanceMetadataNotFound(id=volume_id)

    return rows


@require_context
@require_volume_exists
def volume_glance_metadata_get(context, volume_id):
    """Return the Glance metadata for the specified volume."""

    return _volume_glance_metadata_get(context, volume_id)


@require_context
@require_snapshot_exists
def _volume_snapshot_glance_metadata_get(context, snapshot_id, session=None):
    rows = model_query(context, models.VolumeGlanceMetadata, session=session).\
        filter_by(snapshot_id=snapshot_id).\
        filter_by(deleted=False).\
        all()

    if not rows:
        raise exception.GlanceMetadataNotFound(id=snapshot_id)

    return rows


@require_context
@require_snapshot_exists
def volume_snapshot_glance_metadata_get(context, snapshot_id):
    """Return the Glance metadata for the specified snapshot."""

    return _volume_snapshot_glance_metadata_get(context, snapshot_id)


@require_context
@require_volume_exists
def volume_glance_metadata_create(context, volume_id, key, value):
    """Update the Glance metadata for a volume by adding a new key:value pair.

    This API does not support changing the value of a key once it has been
    created.
    """

    session = get_session()
    with session.begin():
        rows = session.query(models.VolumeGlanceMetadata).\
            filter_by(volume_id=volume_id).\
            filter_by(key=key).\
            filter_by(deleted=False).all()

        if len(rows) > 0:
            raise exception.GlanceMetadataExists(key=key,
                                                 volume_id=volume_id)

        vol_glance_metadata = models.VolumeGlanceMetadata()
        vol_glance_metadata.volume_id = volume_id
        vol_glance_metadata.key = key
        vol_glance_metadata.value = str(value)

        vol_glance_metadata.save(session=session)

    return


@require_context
@require_snapshot_exists
def volume_glance_metadata_copy_to_snapshot(context, snapshot_id, volume_id):
    """Update the Glance metadata for a snapshot.

    This copies all of the key:value pairs from the originating volume, to
    ensure that a volume created from the snapshot will retain the
    original metadata.
    """

    session = get_session()
    with session.begin():
        metadata = _volume_glance_metadata_get(context, volume_id,
                                               session=session)
        for meta in metadata:
            vol_glance_metadata = models.VolumeGlanceMetadata()
            vol_glance_metadata.snapshot_id = snapshot_id
            vol_glance_metadata.key = meta['key']
            vol_glance_metadata.value = meta['value']

            vol_glance_metadata.save(session=session)


@require_context
@require_volume_exists
def volume_glance_metadata_copy_from_volume_to_volume(context,
                                                      src_volume_id,
                                                      volume_id):
    """Update the Glance metadata for a volume.

    This copies all all of the key:value pairs from the originating volume,
    to ensure that a volume created from the volume (clone) will
    retain the original metadata.
    """

    session = get_session()
    with session.begin():
        metadata = _volume_glance_metadata_get(context,
                                               src_volume_id,
                                               session=session)
        for meta in metadata:
            vol_glance_metadata = models.VolumeGlanceMetadata()
            vol_glance_metadata.volume_id = volume_id
            vol_glance_metadata.key = meta['key']
            vol_glance_metadata.value = meta['value']

            vol_glance_metadata.save(session=session)


@require_context
@require_volume_exists
def volume_glance_metadata_copy_to_volume(context, volume_id, snapshot_id):
    """Update the Glance metadata from a volume (created from a snapshot) by
    copying all of the key:value pairs from the originating snapshot.

    This is so that the Glance metadata from the original volume is retained.
    """

    session = get_session()
    with session.begin():
        metadata = _volume_snapshot_glance_metadata_get(context, snapshot_id,
                                                        session=session)
        for meta in metadata:
            vol_glance_metadata = models.VolumeGlanceMetadata()
            vol_glance_metadata.volume_id = volume_id
            vol_glance_metadata.key = meta['key']
            vol_glance_metadata.value = meta['value']

            vol_glance_metadata.save(session=session)


@require_context
def volume_glance_metadata_delete_by_volume(context, volume_id):
    model_query(context, models.VolumeGlanceMetadata, read_deleted='no').\
        filter_by(volume_id=volume_id).\
        update({'deleted': True,
                'deleted_at': timeutils.utcnow(),
                'updated_at': literal_column('updated_at')})


@require_context
def volume_glance_metadata_delete_by_snapshot(context, snapshot_id):
    model_query(context, models.VolumeGlanceMetadata, read_deleted='no').\
        filter_by(snapshot_id=snapshot_id).\
        update({'deleted': True,
                'deleted_at': timeutils.utcnow(),
                'updated_at': literal_column('updated_at')})


###############################


@require_context
def backup_get(context, backup_id):
    result = model_query(context, models.Backup, project_only=True).\
        filter_by(id=backup_id).\
        first()

    if not result:
        raise exception.BackupNotFound(backup_id=backup_id)

    return result


@require_admin_context
def backup_get_all(context):
    return model_query(context, models.Backup).all()


@require_admin_context
def backup_get_all_by_host(context, host):
    return model_query(context, models.Backup).filter_by(host=host).all()


@require_context
def backup_get_all_by_project(context, project_id):
    authorize_project_context(context, project_id)

    return model_query(context, models.Backup).\
        filter_by(project_id=project_id).all()


@require_context
def backup_create(context, values):
    backup = models.Backup()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())
    backup.update(values)
    backup.save()
    return backup


@require_context
def backup_update(context, backup_id, values):
    session = get_session()
    with session.begin():
        backup = model_query(context, models.Backup,
                             session=session, read_deleted="yes").\
            filter_by(id=backup_id).first()

        if not backup:
            raise exception.BackupNotFound(
                _("No backup with id %s") % backup_id)

        backup.update(values)
        backup.save(session=session)
    return backup


@require_admin_context
def backup_destroy(context, backup_id):
    model_query(context, models.Backup).\
        filter_by(id=backup_id).\
        update({'status': 'deleted',
                'deleted': True,
                'deleted_at': timeutils.utcnow(),
                'updated_at': literal_column('updated_at')})


###############################


@require_context
def _transfer_get(context, transfer_id, session=None):
    query = model_query(context, models.Transfer,
                        session=session).\
        filter_by(id=transfer_id)

    if not is_admin_context(context):
        volume = models.Volume
        query = query.filter(models.Transfer.volume_id == volume.id,
                             volume.project_id == context.project_id)

    result = query.first()

    if not result:
        raise exception.TransferNotFound(transfer_id=transfer_id)

    return result


@require_context
def transfer_get(context, transfer_id):
    return _transfer_get(context, transfer_id)


def _translate_transfers(transfers):
    results = []
    for transfer in transfers:
        r = {}
        r['id'] = transfer['id']
        r['volume_id'] = transfer['volume_id']
        r['display_name'] = transfer['display_name']
        r['created_at'] = transfer['created_at']
        r['deleted'] = transfer['deleted']
        results.append(r)
    return results


@require_admin_context
def transfer_get_all(context):
    results = model_query(context, models.Transfer).all()
    return _translate_transfers(results)


@require_context
def transfer_get_all_by_project(context, project_id):
    authorize_project_context(context, project_id)

    query = model_query(context, models.Transfer).\
        filter(models.Volume.id == models.Transfer.volume_id,
               models.Volume.project_id == project_id)
    results = query.all()
    return _translate_transfers(results)


@require_context
def transfer_create(context, values):
    transfer = models.Transfer()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())
    session = get_session()
    with session.begin():
        volume_ref = _volume_get(context,
                                 values['volume_id'],
                                 session=session)
        if volume_ref['status'] != 'available':
            msg = _('Volume must be available')
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)
        volume_ref['status'] = 'awaiting-transfer'
        transfer.update(values)
        transfer.save(session=session)
        volume_ref.update(volume_ref)
        volume_ref.save(session=session)
    return transfer


@require_context
def transfer_destroy(context, transfer_id):
    session = get_session()
    with session.begin():
        transfer_ref = _transfer_get(context,
                                     transfer_id,
                                     session=session)
        volume_ref = _volume_get(context,
                                 transfer_ref['volume_id'],
                                 session=session)
        # If the volume state is not 'awaiting-transfer' don't change it, but
        # we can still mark the transfer record as deleted.
        if volume_ref['status'] != 'awaiting-transfer':
            msg = _('Volume in unexpected state %s, '
                    'expected awaiting-transfer') % volume_ref['status']
            LOG.error(msg)
        else:
            volume_ref['status'] = 'available'
        volume_ref.update(volume_ref)
        volume_ref.save(session=session)
        model_query(context, models.Transfer, session=session).\
            filter_by(id=transfer_id).\
            update({'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})


@require_context
def transfer_accept(context, transfer_id, user_id, project_id):
    session = get_session()
    with session.begin():
        transfer_ref = _transfer_get(context, transfer_id, session)
        volume_id = transfer_ref['volume_id']
        volume_ref = _volume_get(context, volume_id, session=session)
        if volume_ref['status'] != 'awaiting-transfer':
            volume_status = volume_ref['status']
            msg = _('Transfer %(transfer_id)s: Volume id %(volume_id)s in '
                    'unexpected state %(status)s, expected '
                    'awaiting-transfer') % {'transfer_id': transfer_id,
                                            'volume_id': volume_ref['id'],
                                            'status': volume_ref['status']}
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)

        volume_ref['status'] = 'available'
        volume_ref['user_id'] = user_id
        volume_ref['project_id'] = project_id
        volume_ref['updated_at'] = literal_column('updated_at')
        volume_ref.update(volume_ref)
        volume_ref.save(session=session)
        session.query(models.Transfer).\
            filter_by(id=transfer_ref['id']).\
            update({'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})
