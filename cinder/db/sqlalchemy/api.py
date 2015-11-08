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


import datetime as dt
import functools
import sys
import threading
import time
import uuid

from oslo_config import cfg
from oslo_db import exception as db_exc
from oslo_db import options
from oslo_db.sqlalchemy import session as db_session
from oslo_log import log as logging
from oslo_utils import timeutils
from oslo_utils import uuidutils
import osprofiler.sqlalchemy
import six
import sqlalchemy
from sqlalchemy import MetaData
from sqlalchemy import or_
from sqlalchemy.orm import joinedload, joinedload_all
from sqlalchemy.orm import RelationshipProperty
from sqlalchemy.schema import Table
from sqlalchemy.sql.expression import desc
from sqlalchemy.sql.expression import literal_column
from sqlalchemy.sql.expression import true
from sqlalchemy.sql import func
from sqlalchemy.sql import sqltypes

from cinder.api import common
from cinder.common import sqlalchemyutils
from cinder.db.sqlalchemy import models
from cinder import exception
from cinder.i18n import _, _LW, _LE, _LI


CONF = cfg.CONF
CONF.import_group("profiler", "cinder.service")
LOG = logging.getLogger(__name__)

options.set_defaults(CONF, connection='sqlite:///$state_path/cinder.sqlite')

_LOCK = threading.Lock()
_FACADE = None


def _create_facade_lazily():
    global _LOCK
    with _LOCK:
        global _FACADE
        if _FACADE is None:
            _FACADE = db_session.EngineFacade(
                CONF.database.connection,
                **dict(CONF.database)
            )

            if CONF.profiler.profiler_enabled:
                if CONF.profiler.trace_sqlalchemy:
                    osprofiler.sqlalchemy.add_tracing(sqlalchemy,
                                                      _FACADE.get_engine(),
                                                      "db")

        return _FACADE


def get_engine():
    facade = _create_facade_lazily()
    return facade.get_engine()


def get_session(**kwargs):
    facade = _create_facade_lazily()
    return facade.get_session(**kwargs)


def dispose_engine():
    get_engine().dispose()

_DEFAULT_QUOTA_NAME = 'default'


def get_backend():
    """The backend is this module itself."""

    return sys.modules[__name__]


def is_admin_context(context):
    """Indicates if the request context is an administrator."""
    if not context:
        LOG.warning(_LW('Use of empty request context is deprecated'),
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


def _retry_on_deadlock(f):
    """Decorator to retry a DB API call if Deadlock was received."""
    @functools.wraps(f)
    def wrapped(*args, **kwargs):
        while True:
            try:
                return f(*args, **kwargs)
            except db_exc.DBDeadlock:
                LOG.warning(_LW("Deadlock detected when running "
                                "'%(func_name)s': Retrying..."),
                            dict(func_name=f.__name__))
                # Retry!
                time.sleep(0.5)
                continue
    functools.update_wrapper(wrapped, f)
    return wrapped


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
    (volumes, _gigs) = _volume_data_get_for_project(
        context, project_id, volume_type_id=volume_type_id, session=session)
    key = 'volumes'
    if volume_type_name:
        key += '_' + volume_type_name
    return {key: volumes}


def _sync_snapshots(context, project_id, session, volume_type_id=None,
                    volume_type_name=None):
    (snapshots, _gigs) = _snapshot_data_get_for_project(
        context, project_id, volume_type_id=volume_type_id, session=session)
    key = 'snapshots'
    if volume_type_name:
        key += '_' + volume_type_name
    return {key: snapshots}


def _sync_backups(context, project_id, session, volume_type_id=None,
                  volume_type_name=None):
    (backups, _gigs) = _backup_data_get_for_project(
        context, project_id, volume_type_id=volume_type_id, session=session)
    key = 'backups'
    return {key: backups}


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


def _sync_consistencygroups(context, project_id, session,
                            volume_type_id=None,
                            volume_type_name=None):
    (_junk, groups) = _consistencygroup_data_get_for_project(
        context, project_id, session=session)
    key = 'consistencygroups'
    return {key: groups}


def _sync_backup_gigabytes(context, project_id, session, volume_type_id=None,
                           volume_type_name=None):
    key = 'backup_gigabytes'
    (_junk, backup_gigs) = _backup_data_get_for_project(
        context, project_id, volume_type_id=volume_type_id, session=session)
    return {key: backup_gigs}


QUOTA_SYNC_FUNCTIONS = {
    '_sync_volumes': _sync_volumes,
    '_sync_snapshots': _sync_snapshots,
    '_sync_gigabytes': _sync_gigabytes,
    '_sync_consistencygroups': _sync_consistencygroups,
    '_sync_backups': _sync_backups,
    '_sync_backup_gigabytes': _sync_backup_gigabytes
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
def service_get_all_by_topic(context, topic, disabled=None):
    query = model_query(
        context, models.Service, read_deleted="no").\
        filter_by(topic=topic)

    if disabled is not None:
        query = query.filter_by(disabled=disabled)

    return query.all()


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
def service_get_by_args(context, host, binary):
    results = model_query(context, models.Service).\
        filter_by(host=host).\
        filter_by(binary=binary).\
        all()

    for result in results:
        if host == result['host']:
            return result

    raise exception.HostBinaryNotFound(host=host, binary=binary)


@require_admin_context
def service_create(context, values):
    service_ref = models.Service()
    service_ref.update(values)
    if not CONF.enable_new_services:
        service_ref.disabled = True

    session = get_session()
    with session.begin():
        service_ref.save(session)
        return service_ref


@require_admin_context
def service_update(context, service_id, values):
    session = get_session()
    with session.begin():
        service_ref = _service_get(context, service_id, session=session)
        if ('disabled' in values):
            service_ref['modified_at'] = timeutils.utcnow()
            service_ref['updated_at'] = literal_column('updated_at')
        service_ref.update(values)
        return service_ref


###################


def _metadata_refs(metadata_dict, meta_class):
    metadata_refs = []
    if metadata_dict:
        for k, v in metadata_dict.items():
            metadata_ref = meta_class()
            metadata_ref['key'] = k
            metadata_ref['value'] = v
            metadata_refs.append(metadata_ref)
    return metadata_refs


def _dict_with_extra_specs_if_authorized(context, inst_type_query):
    """Convert type query result to dict with extra_spec and rate_limit.

    Takes a volume type query returned by sqlalchemy and returns it
    as a dictionary, converting the extra_specs entry from a list
    of dicts.  NOTE the contents of extra-specs are admin readable
    only.  If the context passed in for this request is not admin
    then we will return an empty extra-specs dict rather than
    providing the admin only details.

    Example response with admin context:

    'extra_specs' : [{'key': 'k1', 'value': 'v1', ...}, ...]
    to a single dict:
    'extra_specs' : {'k1': 'v1'}

    """

    inst_type_dict = dict(inst_type_query)
    if not is_admin_context(context):
        del(inst_type_dict['extra_specs'])
    else:
        extra_specs = {x['key']: x['value']
                       for x in inst_type_query['extra_specs']}
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

    for (key, value) in values.items():
        iscsi_target_ref[key] = value
    session = get_session()

    try:
        with session.begin():
            session.add(iscsi_target_ref)
            return iscsi_target_ref
    except db_exc.DBDuplicateEntry:
        LOG.debug("Can not add duplicate IscsiTarget.")
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


@require_context
def quota_allocated_get_all_by_project(context, project_id):
    rows = model_query(context, models.Quota, read_deleted='no').filter_by(
        project_id=project_id).all()
    result = {'project_id': project_id}
    for row in rows:
        result[row.resource] = row.allocated
    return result


@require_admin_context
def quota_create(context, project_id, resource, limit, allocated):
    quota_ref = models.Quota()
    quota_ref.project_id = project_id
    quota_ref.resource = resource
    quota_ref.hard_limit = limit
    if allocated:
        quota_ref.allocated = allocated

    session = get_session()
    with session.begin():
        quota_ref.save(session)
        return quota_ref


@require_admin_context
def quota_update(context, project_id, resource, limit):
    session = get_session()
    with session.begin():
        quota_ref = _quota_get(context, project_id, resource, session=session)
        quota_ref.hard_limit = limit
        return quota_ref


@require_admin_context
def quota_allocated_update(context, project_id, resource, allocated):
    session = get_session()
    with session.begin():
        quota_ref = _quota_get(context, project_id, resource, session=session)
        quota_ref.allocated = allocated
        return quota_ref


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

    session = get_session()
    with session.begin():
        quota_class_ref.save(session)
        return quota_class_ref


@require_admin_context
def quota_class_update(context, class_name, resource, limit):
    session = get_session()
    with session.begin():
        quota_class_ref = _quota_class_get(context, class_name, resource,
                                           session=session)
        quota_class_ref.hard_limit = limit
        return quota_class_ref


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
    return {row.resource: row for row in rows}


@require_context
@_retry_on_deadlock
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

    if unders:
        LOG.warning(_LW("Change will make usage less than 0 for the following "
                        "resources: %s"), unders)
    if overs:
        usages = {k: dict(in_use=v['in_use'], reserved=v['reserved'])
                  for k, v in usages.items()}
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
@_retry_on_deadlock
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


@require_context
@_retry_on_deadlock
def reservation_rollback(context, reservations, project_id=None):
    session = get_session()
    with session.begin():
        usages = _get_quota_usages(context, session, project_id)

        for reservation in _quota_reservations(session, context, reservations):
            usage = usages[reservation.resource]
            if reservation.delta >= 0:
                usage.reserved -= reservation.delta

            reservation.delete(session=session)


def quota_destroy_by_project(*args, **kwargs):
    """Destroy all limit quotas associated with a project.

    Leaves usage and reservation quotas intact.
    """
    quota_destroy_all_by_project(only_quotas=True, *args, **kwargs)


@require_admin_context
@_retry_on_deadlock
def quota_destroy_all_by_project(context, project_id, only_quotas=False):
    """Destroy all quotas associated with a project.

    This includes limit quotas, usage quotas and reservation quotas.
    Optionally can only remove limit quotas and leave other types as they are.

    :param context: The request context, for access checks.
    :param project_id: The ID of the project being deleted.
    :param only_quotas: Only delete limit quotas, leave other types intact.
    """
    session = get_session()
    with session.begin():
        quotas = model_query(context, models.Quota, session=session,
                             read_deleted="no").\
            filter_by(project_id=project_id).\
            all()

        for quota_ref in quotas:
            quota_ref.delete(session=session)

        if only_quotas:
            return

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
@_retry_on_deadlock
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
def volume_attach(context, values):
    volume_attachment_ref = models.VolumeAttachment()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())

    volume_attachment_ref.update(values)
    session = get_session()
    with session.begin():
        volume_attachment_ref.save(session=session)
        return volume_attachment_get(context, values['id'],
                                     session=session)


@require_admin_context
def volume_attached(context, attachment_id, instance_uuid, host_name,
                    mountpoint, attach_mode='rw'):
    """This method updates a volume attachment entry.

    This function saves the information related to a particular
    attachment for a volume.  It also updates the volume record
    to mark the volume as attached.

    """
    if instance_uuid and not uuidutils.is_uuid_like(instance_uuid):
        raise exception.InvalidUUID(uuid=instance_uuid)

    session = get_session()
    with session.begin():
        volume_attachment_ref = volume_attachment_get(context, attachment_id,
                                                      session=session)

        volume_attachment_ref['mountpoint'] = mountpoint
        volume_attachment_ref['attach_status'] = 'attached'
        volume_attachment_ref['instance_uuid'] = instance_uuid
        volume_attachment_ref['attached_host'] = host_name
        volume_attachment_ref['attach_time'] = timeutils.utcnow()
        volume_attachment_ref['attach_mode'] = attach_mode

        volume_ref = _volume_get(context, volume_attachment_ref['volume_id'],
                                 session=session)
        volume_attachment_ref.save(session=session)

        volume_ref['status'] = 'in-use'
        volume_ref['attach_status'] = 'attached'
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
        session.add(volume_ref)

    return _volume_get(context, values['id'], session=session)


def get_booleans_for_table(table_name):
    booleans = set()
    table = getattr(models, table_name.capitalize())
    if hasattr(table, '__table__'):
        columns = table.__table__.columns
        for column in columns:
            if isinstance(column.type, sqltypes.Boolean):
                booleans.add(column.name)

    return booleans


@require_admin_context
def volume_data_get_for_host(context, host, count_only=False):
    host_attr = models.Volume.host
    conditions = [host_attr == host, host_attr.op('LIKE')(host + '#%')]
    if count_only:
        result = model_query(context,
                             func.count(models.Volume.id),
                             read_deleted="no").filter(
            or_(*conditions)).first()
        return result[0] or 0
    else:
        result = model_query(context,
                             func.count(models.Volume.id),
                             func.sum(models.Volume.size),
                             read_deleted="no").filter(
            or_(*conditions)).first()
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
def _backup_data_get_for_project(context, project_id, volume_type_id=None,
                                 session=None):
    query = model_query(context,
                        func.count(models.Backup.id),
                        func.sum(models.Backup.size),
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
    """Swap almost all columns between dest and source.

    We swap fields between source and destination at the end of migration
    because we want to keep the original volume id in the DB but now pointing
    to the migrated volume.

    Original volume will be deleted, after this method original volume will be
    pointed by dest_vol_id, so we set its status and migrating_status to
    'deleting'.  We change status here to keep it in sync with migration_status
    which must be changed here.

    param src_vol_id:: ID of the migration original volume
    param dest_vol_id: ID of the migration destination volume
    returns: Tuple with new source and destination ORM objects.  Source will be
             the migrated volume and destination will be original volume that
             will be deleted.
    """
    session = get_session()
    with session.begin():
        src_volume_ref = _volume_get(context, src_vol_id, session=session,
                                     joined_load=False)
        src_original_data = dict(src_volume_ref.iteritems())
        dest_volume_ref = _volume_get(context, dest_vol_id, session=session,
                                      joined_load=False)

        # NOTE(rpodolyaka): we should copy only column values, while model
        #                   instances also have relationships attributes, which
        #                   should be ignored
        def is_column(inst, attr):
            return attr in inst.__class__.__table__.columns

        for key, value in dest_volume_ref.iteritems():
            value_to_dst = src_original_data.get(key)
            # The implementation of update_migrated_volume will decide the
            # values for _name_id and provider_location.
            if (key in ('id', 'provider_location')
                    or not is_column(dest_volume_ref, key)):
                continue

            # Destination must have a _name_id since the id no longer matches
            # the volume.  If it doesn't have a _name_id we set one.
            elif key == '_name_id':
                if not dest_volume_ref._name_id:
                    setattr(dest_volume_ref, key, src_volume_ref.id)
                continue
            elif key == 'migration_status':
                value = None
                value_to_dst = 'deleting'
            elif key == 'display_description':
                value_to_dst = 'migration src for ' + src_volume_ref.id
            elif key == 'status':
                value_to_dst = 'deleting'

            setattr(src_volume_ref, key, value)
            setattr(dest_volume_ref, key, value_to_dst)
    return src_volume_ref, dest_volume_ref


@require_admin_context
@_retry_on_deadlock
def volume_destroy(context, volume_id):
    session = get_session()
    now = timeutils.utcnow()
    with session.begin():
        model_query(context, models.Volume, session=session).\
            filter_by(id=volume_id).\
            update({'status': 'deleted',
                    'deleted': True,
                    'deleted_at': now,
                    'updated_at': literal_column('updated_at'),
                    'migration_status': None})
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
def volume_detach(context, attachment_id):
    session = get_session()
    with session.begin():
        volume_attachment_ref = volume_attachment_get(context, attachment_id,
                                                      session=session)
        volume_attachment_ref['attach_status'] = 'detaching'
        volume_attachment_ref.save(session=session)


@require_admin_context
def volume_detached(context, volume_id, attachment_id):
    """This updates a volume attachment and marks it as detached.

    This method also ensures that the volume entry is correctly
    marked as either still attached/in-use or detached/available
    if this was the last detachment made.

    """
    session = get_session()
    with session.begin():
        attachment = None
        try:
            attachment = volume_attachment_get(context, attachment_id,
                                               session=session)
        except exception.VolumeAttachmentNotFound:
            pass

        # If this is already detached, attachment will be None
        if attachment:
            now = timeutils.utcnow()
            attachment['attach_status'] = 'detached'
            attachment['detach_time'] = now
            attachment['deleted'] = True
            attachment['deleted_at'] = now
            attachment.save(session=session)

        attachment_list = volume_attachment_get_used_by_volume_id(
            context, volume_id, session=session)
        remain_attachment = False
        if attachment_list and len(attachment_list) > 0:
            remain_attachment = True

        volume_ref = _volume_get(context, volume_id, session=session)
        if not remain_attachment:
            # Hide status update from user if we're performing volume migration
            # or uploading it to image
            if ((not volume_ref['migration_status'] and
                    not (volume_ref['status'] == 'uploading')) or
                    volume_ref['migration_status'] in ('success', 'error')):
                volume_ref['status'] = 'available'

            volume_ref['attach_status'] = 'detached'
            volume_ref.save(session=session)
        else:
            # Volume is still attached
            volume_ref['status'] = 'in-use'
            volume_ref['attach_status'] = 'attached'
            volume_ref.save(session=session)


@require_context
def _volume_get_query(context, session=None, project_only=False,
                      joined_load=True):
    """Get the query to retrieve the volume.

    :param context: the context used to run the method _volume_get_query
    :param session: the session to use
    :param project_only: the boolean used to decide whether to query the
                         volume in the current project or all projects
    :param joined_load: the boolean used to decide whether the query loads
                        the other models, which join the volume model in
                        the database. Currently, the False value for this
                        parameter is specially for the case of updating
                        database during volume migration
    :returns: updated query or None
    """
    if not joined_load:
        return model_query(context, models.Volume, session=session,
                           project_only=project_only)
    if is_admin_context(context):
        return model_query(context, models.Volume, session=session,
                           project_only=project_only).\
            options(joinedload('volume_metadata')).\
            options(joinedload('volume_admin_metadata')).\
            options(joinedload('volume_type')).\
            options(joinedload('volume_attachment')).\
            options(joinedload('consistencygroup'))
    else:
        return model_query(context, models.Volume, session=session,
                           project_only=project_only).\
            options(joinedload('volume_metadata')).\
            options(joinedload('volume_type')).\
            options(joinedload('volume_attachment')).\
            options(joinedload('consistencygroup'))


@require_context
def _volume_get(context, volume_id, session=None, joined_load=True):
    result = _volume_get_query(context, session=session, project_only=True,
                               joined_load=joined_load)
    if joined_load:
        result = result.options(joinedload('volume_type.extra_specs'))
    result = result.filter_by(id=volume_id).first()

    if not result:
        raise exception.VolumeNotFound(volume_id=volume_id)

    return result


@require_context
def volume_attachment_get(context, attachment_id, session=None):
    result = model_query(context, models.VolumeAttachment,
                         session=session).\
        filter_by(id=attachment_id).\
        first()
    if not result:
        raise exception.VolumeAttachmentNotFound(filter='attachment_id = %s' %
                                                 attachment_id)
    return result


@require_context
def volume_attachment_get_used_by_volume_id(context, volume_id, session=None):
    result = model_query(context, models.VolumeAttachment,
                         session=session).\
        filter_by(volume_id=volume_id).\
        filter(models.VolumeAttachment.attach_status != 'detached').\
        all()
    return result


@require_context
def volume_attachment_get_by_host(context, volume_id, host):
    session = get_session()
    with session.begin():
        result = model_query(context, models.VolumeAttachment,
                             session=session).\
            filter_by(volume_id=volume_id).\
            filter_by(attached_host=host).\
            filter(models.VolumeAttachment.attach_status != 'detached').\
            first()
        return result


@require_context
def volume_attachment_get_by_instance_uuid(context, volume_id, instance_uuid):
    session = get_session()
    with session.begin():
        result = model_query(context, models.VolumeAttachment,
                             session=session).\
            filter_by(volume_id=volume_id).\
            filter_by(instance_uuid=instance_uuid).\
            filter(models.VolumeAttachment.attach_status != 'detached').\
            first()
        return result


@require_context
def volume_get(context, volume_id):
    return _volume_get(context, volume_id)


@require_admin_context
def volume_get_all(context, marker, limit, sort_keys=None, sort_dirs=None,
                   filters=None, offset=None):
    """Retrieves all volumes.

    If no sort parameters are specified then the returned volumes are sorted
    first by the 'created_at' key and then by the 'id' key in descending
    order.

    :param context: context to query under
    :param marker: the last item of the previous page, used to determine the
                   next page of results to return
    :param limit: maximum number of items to return
    :param sort_keys: list of attributes by which results should be sorted,
                      paired with corresponding item in sort_dirs
    :param sort_dirs: list of directions in which results should be sorted,
                      paired with corresponding item in sort_keys
    :param filters: dictionary of filters; values that are in lists, tuples,
                    or sets cause an 'IN' operation, while exact matching
                    is used for other values, see _process_volume_filters
                    function for more information
    :returns: list of matching volumes
    """
    session = get_session()
    with session.begin():
        # Generate the query
        query = _generate_paginate_query(context, session, marker, limit,
                                         sort_keys, sort_dirs, filters, offset)
        # No volumes would match, return empty list
        if query is None:
            return []
        return query.all()


@require_admin_context
def volume_get_all_by_host(context, host, filters=None):
    """Retrieves all volumes hosted on a host.

    :param context: context to query under
    :param host: host for all volumes being retrieved
    :param filters: dictionary of filters; values that are in lists, tuples,
                    or sets cause an 'IN' operation, while exact matching
                    is used for other values, see _process_volume_filters
                    function for more information
    :returns: list of matching volumes
    """
    # As a side effect of the introduction of pool-aware scheduler,
    # newly created volumes will have pool information appended to
    # 'host' field of a volume record. So a volume record in DB can
    # now be either form below:
    #     Host
    #     Host#Pool
    if host and isinstance(host, six.string_types):
        session = get_session()
        with session.begin():
            host_attr = getattr(models.Volume, 'host')
            conditions = [host_attr == host,
                          host_attr.op('LIKE')(host + '#%')]
            query = _volume_get_query(context).filter(or_(*conditions))
            if filters:
                query = _process_volume_filters(query, filters)
                # No volumes would match, return empty list
                if query is None:
                    return []
            return query.all()
    elif not host:
        return []


@require_context
def volume_get_all_by_group(context, group_id, filters=None):
    """Retrieves all volumes associated with the group_id.

    :param context: context to query under
    :param group_id: group ID for all volumes being retrieved
    :param filters: dictionary of filters; values that are in lists, tuples,
                    or sets cause an 'IN' operation, while exact matching
                    is used for other values, see _process_volume_filters
                    function for more information
    :returns: list of matching volumes
    """
    query = _volume_get_query(context).filter_by(consistencygroup_id=group_id)
    if filters:
        query = _process_volume_filters(query, filters)
        # No volumes would match, return empty list
        if query is None:
            return []
    return query.all()


@require_context
def volume_get_all_by_project(context, project_id, marker, limit,
                              sort_keys=None, sort_dirs=None, filters=None,
                              offset=None):
    """Retrieves all volumes in a project.

    If no sort parameters are specified then the returned volumes are sorted
    first by the 'created_at' key and then by the 'id' key in descending
    order.

    :param context: context to query under
    :param project_id: project for all volumes being retrieved
    :param marker: the last item of the previous page, used to determine the
                   next page of results to return
    :param limit: maximum number of items to return
    :param sort_keys: list of attributes by which results should be sorted,
                      paired with corresponding item in sort_dirs
    :param sort_dirs: list of directions in which results should be sorted,
                      paired with corresponding item in sort_keys
    :param filters: dictionary of filters; values that are in lists, tuples,
                    or sets cause an 'IN' operation, while exact matching
                    is used for other values, see _process_volume_filters
                    function for more information
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
                                         sort_keys, sort_dirs, filters, offset)
        # No volumes would match, return empty list
        if query is None:
            return []
        return query.all()


def _generate_paginate_query(context, session, marker, limit, sort_keys,
                             sort_dirs, filters, offset=None,
                             paginate_type=models.Volume):
    """Generate the query to include the filters and the paginate options.

    Returns a query with sorting / pagination criteria added or None
    if the given filters will not yield any results.

    :param context: context to query under
    :param session: the session to use
    :param marker: the last item of the previous page; we returns the next
                    results after this value.
    :param limit: maximum number of items to return
    :param sort_keys: list of attributes by which results should be sorted,
                      paired with corresponding item in sort_dirs
    :param sort_dirs: list of directions in which results should be sorted,
                      paired with corresponding item in sort_keys
    :param filters: dictionary of filters; values that are in lists, tuples,
                    or sets cause an 'IN' operation, while exact matching
                    is used for other values, see _process_volume_filters
                    function for more information
    :param offset: number of items to skip
    :param paginate_type: type of pagination to generate
    :returns: updated query or None
    """
    get_query, process_filters, get = PAGINATION_HELPERS[paginate_type]

    sort_keys, sort_dirs = process_sort_params(sort_keys,
                                               sort_dirs,
                                               default_dir='desc')
    query = get_query(context, session=session)

    if filters:
        query = process_filters(query, filters)
        if query is None:
            return None

    marker_volume = None
    if marker is not None:
        marker_volume = get(context, marker, session)

    return sqlalchemyutils.paginate_query(query, paginate_type, limit,
                                          sort_keys,
                                          marker=marker_volume,
                                          sort_dirs=sort_dirs,
                                          offset=offset)


def _process_volume_filters(query, filters):
    """Common filter processing for Volume queries.

    Filter values that are in lists, tuples, or sets cause an 'IN' operator
    to be used, while exact matching ('==' operator) is used for other values.

    A filter key/value of 'no_migration_targets'=True causes volumes with
    either a NULL 'migration_status' or a 'migration_status' that does not
    start with 'target:' to be retrieved.

    A 'metadata' filter key must correspond to a dictionary value of metadata
    key-value pairs.

    :param query: Model query to use
    :param filters: dictionary of filters
    :returns: updated query or None
    """
    filters = filters.copy()

    # 'no_migration_targets' is unique, must be either NULL or
    # not start with 'target:'
    if filters.get('no_migration_targets', False):
        filters.pop('no_migration_targets')
        try:
            column_attr = getattr(models.Volume, 'migration_status')
            conditions = [column_attr == None,  # noqa
                          column_attr.op('NOT LIKE')('target:%')]
            query = query.filter(or_(*conditions))
        except AttributeError:
            LOG.debug("'migration_status' column could not be found.")
            return None

    # Apply exact match filters for everything else, ensure that the
    # filter value exists on the model
    for key in filters.keys():
        # metadata is unique, must be a dict
        if key == 'metadata':
            if not isinstance(filters[key], dict):
                LOG.debug("'metadata' filter value is not valid.")
                return None
            continue
        try:
            column_attr = getattr(models.Volume, key)
            # Do not allow relationship properties since those require
            # schema specific knowledge
            prop = getattr(column_attr, 'property')
            if isinstance(prop, RelationshipProperty):
                LOG.debug(("'%s' filter key is not valid, "
                           "it maps to a relationship."), key)
                return None
        except AttributeError:
            LOG.debug("'%s' filter key is not valid.", key)
            return None

    # Holds the simple exact matches
    filter_dict = {}

    # Iterate over all filters, special case the filter if necessary
    for key, value in filters.items():
        if key == 'metadata':
            # model.VolumeMetadata defines the backref to Volumes as
            # 'volume_metadata' or 'volume_admin_metadata', use those as
            # column attribute keys
            col_attr = getattr(models.Volume, 'volume_metadata')
            col_ad_attr = getattr(models.Volume, 'volume_admin_metadata')
            for k, v in value.items():
                query = query.filter(or_(col_attr.any(key=k, value=v),
                                         col_ad_attr.any(key=k, value=v)))
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
    return query


def process_sort_params(sort_keys, sort_dirs, default_keys=None,
                        default_dir='asc'):
    """Process the sort parameters to include default keys.

    Creates a list of sort keys and a list of sort directions. Adds the default
    keys to the end of the list if they are not already included.

    When adding the default keys to the sort keys list, the associated
    direction is:
    1) The first element in the 'sort_dirs' list (if specified), else
    2) 'default_dir' value (Note that 'asc' is the default value since this is
    the default in sqlalchemy.utils.paginate_query)

    :param sort_keys: List of sort keys to include in the processed list
    :param sort_dirs: List of sort directions to include in the processed list
    :param default_keys: List of sort keys that need to be included in the
                         processed list, they are added at the end of the list
                         if not already specified.
    :param default_dir: Sort direction associated with each of the default
                        keys that are not supplied, used when they are added
                        to the processed list
    :returns: list of sort keys, list of sort directions
    :raise exception.InvalidInput: If more sort directions than sort keys
                                   are specified or if an invalid sort
                                   direction is specified
    """
    if default_keys is None:
        default_keys = ['created_at', 'id']

    # Determine direction to use for when adding default keys
    if sort_dirs and len(sort_dirs):
        default_dir_value = sort_dirs[0]
    else:
        default_dir_value = default_dir

    # Create list of keys (do not modify the input list)
    if sort_keys:
        result_keys = list(sort_keys)
    else:
        result_keys = []

    # If a list of directions is not provided, use the default sort direction
    # for all provided keys.
    if sort_dirs:
        result_dirs = []
        # Verify sort direction
        for sort_dir in sort_dirs:
            if sort_dir not in ('asc', 'desc'):
                msg = _("Unknown sort direction, must be 'desc' or 'asc'.")
                raise exception.InvalidInput(reason=msg)
            result_dirs.append(sort_dir)
    else:
        result_dirs = [default_dir_value for _sort_key in result_keys]

    # Ensure that the key and direction length match
    while len(result_dirs) < len(result_keys):
        result_dirs.append(default_dir_value)
    # Unless more direction are specified, which is an error
    if len(result_dirs) > len(result_keys):
        msg = _("Sort direction array size exceeds sort key array size.")
        raise exception.InvalidInput(reason=msg)

    # Ensure defaults are included
    for key in default_keys:
        if key not in result_keys:
            result_keys.append(key)
            result_dirs.append(default_dir_value)

    return result_keys, result_dirs


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

        return volume_ref


@require_context
def volume_attachment_update(context, attachment_id, values):
    session = get_session()
    with session.begin():
        volume_attachment_ref = volume_attachment_get(context, attachment_id,
                                                      session=session)
        volume_attachment_ref.update(values)
        volume_attachment_ref.save(session=session)
        return volume_attachment_ref


def volume_update_status_based_on_attachment(context, volume_id):
    """Update volume status based on attachment.

    Get volume and check if 'volume_attachment' parameter is present in volume.
    If 'volume_attachment' is None then set volume status to 'available'
    else set volume status to 'in-use'.

    :param context: context to query under
    :param volume_id: id of volume to be updated
    :returns: updated volume
    """
    session = get_session()
    with session.begin():
        volume_ref = _volume_get(context, volume_id, session=session)
        # We need to get and update volume using same session because
        # there is possibility that instance is deleted between the 'get'
        # and 'update' volume call.
        if not volume_ref['volume_attachment']:
            volume_ref.update({'status': 'available'})
        else:
            volume_ref.update({'status': 'in-use'})

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
        if model is models.VolumeGlanceMetadata:
            raise notfound_exec(id=volume_id)
        else:
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
            for meta_key, meta_value in original_metadata.items():
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


def _volume_image_metadata_get_query(context, volume_id, session=None):
    return _volume_x_metadata_get_query(context, volume_id,
                                        models.VolumeGlanceMetadata,
                                        session=session)


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
def _volume_image_metadata_update(context, volume_id, metadata, delete,
                                  session=None):
    return _volume_x_metadata_update(context, volume_id, metadata, delete,
                                     models.VolumeGlanceMetadata,
                                     exception.GlanceMetadataNotFound,
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
@_retry_on_deadlock
def volume_metadata_delete(context, volume_id, key, meta_type):
    if meta_type == common.METADATA_TYPES.user:
        (_volume_user_metadata_get_query(context, volume_id).
            filter_by(key=key).
            update({'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')}))
    elif meta_type == common.METADATA_TYPES.image:
        (_volume_image_metadata_get_query(context, volume_id).
            filter_by(key=key).
            update({'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')}))
    else:
        raise exception.InvalidMetadataType(metadata_type=meta_type,
                                            id=volume_id)


@require_context
@require_volume_exists
@_retry_on_deadlock
def volume_metadata_update(context, volume_id, metadata, delete, meta_type):
    if meta_type == common.METADATA_TYPES.user:
        return _volume_user_metadata_update(context,
                                            volume_id,
                                            metadata,
                                            delete)
    elif meta_type == common.METADATA_TYPES.image:
        return _volume_image_metadata_update(context,
                                             volume_id,
                                             metadata,
                                             delete)
    else:
        raise exception.InvalidMetadataType(metadata_type=meta_type,
                                            id=volume_id)


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
@_retry_on_deadlock
def volume_admin_metadata_delete(context, volume_id, key):
    _volume_admin_metadata_get_query(context, volume_id).\
        filter_by(key=key).\
        update({'deleted': True,
                'deleted_at': timeutils.utcnow(),
                'updated_at': literal_column('updated_at')})


@require_admin_context
@require_volume_exists
@_retry_on_deadlock
def volume_admin_metadata_update(context, volume_id, metadata, delete):
    return _volume_admin_metadata_update(context, volume_id, metadata, delete)


###################


@require_context
def snapshot_create(context, values):
    values['snapshot_metadata'] = _metadata_refs(values.get('metadata'),
                                                 models.SnapshotMetadata)
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())

    session = get_session()
    with session.begin():
        snapshot_ref = models.Snapshot()
        snapshot_ref.update(values)
        session.add(snapshot_ref)

        return _snapshot_get(context, values['id'], session=session)


@require_admin_context
@_retry_on_deadlock
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
def snapshot_get_all(context, filters=None, marker=None, limit=None,
                     sort_keys=None, sort_dirs=None, offset=None):
    """Retrieves all snapshots.

    If no sorting parameters are specified then returned snapshots are sorted
    first by the 'created_at' key and then by the 'id' key in descending
    order.

    :param context: context to query under
    :param filters: dictionary of filters; will do exact matching on values
    :param marker: the last item of the previous page, used to determine the
                   next page of results to return
    :param limit: maximum number of items to return
    :param sort_keys: list of attributes by which results should be sorted,
                      paired with corresponding item in sort_dirs
    :param sort_dirs: list of directions in which results should be sorted,
                      paired with corresponding item in sort_keys
    :returns: list of matching snapshots
    """
    if filters and not is_valid_model_filters(models.Snapshot, filters):
        return []

    session = get_session()
    with session.begin():
        query = _generate_paginate_query(context, session, marker, limit,
                                         sort_keys, sort_dirs, filters,
                                         offset, models.Snapshot)

    # No snapshots would match, return empty list
    if not query:
        return []
    return query.all()


def _snaps_get_query(context, session=None, project_only=False):
    return model_query(context, models.Snapshot, session=session,
                       project_only=project_only).\
        options(joinedload('snapshot_metadata'))


def _process_snaps_filters(query, filters):
    if filters:
        # Ensure that filters' keys exist on the model
        if not is_valid_model_filters(models.Snapshot, filters):
            return None
        query = query.filter_by(**filters)
    return query


@require_context
def snapshot_get_all_for_volume(context, volume_id):
    return model_query(context, models.Snapshot, read_deleted='no',
                       project_only=True).\
        filter_by(volume_id=volume_id).\
        options(joinedload('snapshot_metadata')).\
        all()


@require_context
def snapshot_get_by_host(context, host, filters=None):
    if filters and not is_valid_model_filters(models.Snapshot, filters):
        return []

    query = model_query(context, models.Snapshot, read_deleted='no',
                        project_only=True)
    if filters:
        query = query.filter_by(**filters)

    # As a side effect of the introduction of pool-aware scheduler,
    # newly created volumes will have pool information appended to
    # 'host' field of a volume record. So a volume record in DB can
    # now be either form below:
    #     Host
    #     Host#Pool
    if host and isinstance(host, six.string_types):
        session = get_session()
        with session.begin():
            host_attr = getattr(models.Volume, 'host')
            conditions = [host_attr == host,
                          host_attr.op('LIKE')(host + '#%')]
            query = query.join(models.Snapshot.volume).filter(
                or_(*conditions)).options(joinedload('snapshot_metadata'))
            return query.all()
    elif not host:
        return []


@require_context
def snapshot_get_all_for_cgsnapshot(context, cgsnapshot_id):
    return model_query(context, models.Snapshot, read_deleted='no',
                       project_only=True).\
        filter_by(cgsnapshot_id=cgsnapshot_id).\
        options(joinedload('volume')).\
        options(joinedload('snapshot_metadata')).\
        all()


@require_context
def snapshot_get_all_by_project(context, project_id, filters=None, marker=None,
                                limit=None, sort_keys=None, sort_dirs=None,
                                offset=None):
    """"Retrieves all snapshots in a project.

    If no sorting parameters are specified then returned snapshots are sorted
    first by the 'created_at' key and then by the 'id' key in descending
    order.

    :param context: context to query under
    :param project_id: project for all snapshots being retrieved
    :param filters: dictionary of filters; will do exact matching on values
    :param marker: the last item of the previous page, used to determine the
                   next page of results to return
    :param limit: maximum number of items to return
    :param sort_keys: list of attributes by which results should be sorted,
                      paired with corresponding item in sort_dirs
    :param sort_dirs: list of directions in which results should be sorted,
                      paired with corresponding item in sort_keys
    :returns: list of matching snapshots
    """
    if filters and not is_valid_model_filters(models.Snapshot, filters):
        return []

    authorize_project_context(context, project_id)

    # Add project_id to filters
    filters = filters.copy() if filters else {}
    filters['project_id'] = project_id

    session = get_session()
    with session.begin():
        query = _generate_paginate_query(context, session, marker, limit,
                                         sort_keys, sort_dirs, filters,
                                         offset, models.Snapshot)

    # No snapshots would match, return empty list
    if not query:
        return []

    query = query.options(joinedload('snapshot_metadata'))
    return query.all()


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
    query = query.filter(or_(models.Snapshot.deleted_at == None,  # noqa
                             models.Snapshot.deleted_at > begin))
    query = query.options(joinedload(models.Snapshot.volume))
    query = query.options(joinedload('snapshot_metadata'))
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
        return snapshot_ref

####################


def _snapshot_metadata_get_query(context, snapshot_id, session=None):
    return model_query(context, models.SnapshotMetadata,
                       session=session, read_deleted="no").\
        filter_by(snapshot_id=snapshot_id)


@require_context
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
@_retry_on_deadlock
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
@_retry_on_deadlock
def snapshot_metadata_update(context, snapshot_id, metadata, delete):
    session = get_session()
    with session.begin():
        # Set existing metadata to deleted if delete argument is True
        if delete:
            original_metadata = _snapshot_metadata_get(context, snapshot_id,
                                                       session)
            for meta_key, meta_value in original_metadata.items():
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
            except exception.SnapshotMetadataNotFound:
                meta_ref = models.SnapshotMetadata()
                item.update({"key": meta_key, "snapshot_id": snapshot_id})

            meta_ref.update(item)
            meta_ref.save(session=session)

    return snapshot_metadata_get(context, snapshot_id)

###################


@require_admin_context
def volume_type_create(context, values, projects=None):
    """Create a new volume type.

    In order to pass in extra specs, the values dict should contain a
    'extra_specs' key/value pair:
    {'extra_specs' : {'k1': 'v1', 'k2': 'v2', ...}}
    """
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())

    projects = projects or []

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
            session.add(volume_type_ref)
        except Exception as e:
            raise db_exc.DBError(e)
        for project in set(projects):
            access_ref = models.VolumeTypeProjects()
            access_ref.update({"volume_type_id": volume_type_ref.id,
                               "project_id": project})
            access_ref.save(session=session)
        return volume_type_ref


def _volume_type_get_query(context, session=None, read_deleted=None,
                           expected_fields=None):
    expected_fields = expected_fields or []
    query = model_query(context,
                        models.VolumeTypes,
                        session=session,
                        read_deleted=read_deleted).\
        options(joinedload('extra_specs'))

    if 'projects' in expected_fields:
        query = query.options(joinedload('projects'))

    if not context.is_admin:
        the_filter = [models.VolumeTypes.is_public == true()]
        projects_attr = getattr(models.VolumeTypes, 'projects')
        the_filter.extend([
            projects_attr.any(project_id=context.project_id)
        ])
        query = query.filter(or_(*the_filter))

    return query


@require_admin_context
def volume_type_update(context, volume_type_id, values):
    session = get_session()
    with session.begin():
        # Check it exists
        volume_type_ref = _volume_type_ref_get(context,
                                               volume_type_id,
                                               session)
        if not volume_type_ref:
            raise exception.VolumeTypeNotFound(type_id=volume_type_id)

        # No description change
        if values['description'] is None:
            del values['description']

        # No is_public change
        if values['is_public'] is None:
            del values['is_public']

        # No name change
        if values['name'] is None:
            del values['name']
        else:
            # Volume type name is unique. If change to a name that belongs to
            # a different volume_type , it should be prevented.
            check_vol_type = None
            try:
                check_vol_type = \
                    _volume_type_get_by_name(context,
                                             values['name'],
                                             session=session)
            except exception.VolumeTypeNotFoundByName:
                pass
            else:
                if check_vol_type.get('id') != volume_type_id:
                    raise exception.VolumeTypeExists(id=values['name'])

        volume_type_ref.update(values)
        volume_type_ref.save(session=session)
        volume_type = volume_type_get(context, volume_type_id)

        return volume_type


@require_context
def volume_type_get_all(context, inactive=False, filters=None):
    """Returns a dict describing all volume_types with name as key."""
    filters = filters or {}

    read_deleted = "yes" if inactive else "no"

    query = _volume_type_get_query(context, read_deleted=read_deleted)

    if 'is_public' in filters and filters['is_public'] is not None:
        the_filter = [models.VolumeTypes.is_public == filters['is_public']]
        if filters['is_public'] and context.project_id is not None:
            projects_attr = getattr(models.VolumeTypes, 'projects')
            the_filter.extend([
                projects_attr.any(project_id=context.project_id, deleted=False)
            ])
        if len(the_filter) > 1:
            query = query.filter(or_(*the_filter))
        else:
            query = query.filter(the_filter[0])

    rows = query.order_by("name").all()

    result = {}
    for row in rows:
        result[row['name']] = _dict_with_extra_specs_if_authorized(context,
                                                                   row)

    return result


def _volume_type_get_id_from_volume_type_query(context, id, session=None):
    return model_query(
        context, models.VolumeTypes.id, read_deleted="no",
        session=session, base_model=models.VolumeTypes).\
        filter_by(id=id)


def _volume_type_get_id_from_volume_type(context, id, session=None):
    result = _volume_type_get_id_from_volume_type_query(
        context, id, session=session).first()
    if not result:
        raise exception.VolumeTypeNotFound(volume_type_id=id)
    return result[0]


@require_context
def _volume_type_get(context, id, session=None, inactive=False,
                     expected_fields=None):
    expected_fields = expected_fields or []
    read_deleted = "yes" if inactive else "no"
    result = _volume_type_get_query(
        context, session, read_deleted, expected_fields).\
        filter_by(id=id).\
        first()

    if not result:
        raise exception.VolumeTypeNotFound(volume_type_id=id)

    vtype = _dict_with_extra_specs_if_authorized(context, result)

    if 'projects' in expected_fields:
        vtype['projects'] = [p['project_id'] for p in result['projects']]

    return vtype


@require_context
def volume_type_get(context, id, inactive=False, expected_fields=None):
    """Return a dict describing specific volume_type."""

    return _volume_type_get(context, id,
                            session=None,
                            inactive=inactive,
                            expected_fields=expected_fields)


@require_context
def _volume_type_ref_get(context, id, session=None, inactive=False):
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

    return result


@require_context
def _volume_type_get_by_name(context, name, session=None):
    result = model_query(context, models.VolumeTypes, session=session).\
        options(joinedload('extra_specs')).\
        filter_by(name=name).\
        first()

    if not result:
        raise exception.VolumeTypeNotFoundByName(volume_type_name=name)

    return _dict_with_extra_specs_if_authorized(context, result)


@require_context
def volume_type_get_by_name(context, name):
    """Return a dict describing specific volume_type."""

    return _volume_type_get_by_name(context, name)


@require_context
def volume_types_get_by_name_or_id(context, volume_type_list):
    """Return a dict describing specific volume_type."""
    req_volume_types = []
    for vol_t in volume_type_list:
        if not uuidutils.is_uuid_like(vol_t):
            vol_type = _volume_type_get_by_name(context, vol_t)
        else:
            vol_type = _volume_type_get(context, vol_t)
        req_volume_types.append(vol_type)
    return req_volume_types


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
@_retry_on_deadlock
def volume_type_destroy(context, id):
    session = get_session()
    with session.begin():
        _volume_type_get(context, id, session)
        results = model_query(context, models.Volume, session=session). \
            filter_by(volume_type_id=id).all()
        if results:
            LOG.error(_LE('VolumeType %s deletion failed, '
                          'VolumeType in use.'), id)
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
    query = query.filter(or_(models.Volume.deleted_at == None,  # noqa
                             models.Volume.deleted_at > begin))
    if end:
        query = query.filter(models.Volume.created_at < end)
    if project_id:
        query = query.filter_by(project_id=project_id)

    return query.all()


def _volume_type_access_query(context, session=None):
    return model_query(context, models.VolumeTypeProjects, session=session,
                       read_deleted="no")


@require_admin_context
def volume_type_access_get_all(context, type_id):
    volume_type_id = _volume_type_get_id_from_volume_type(context, type_id)
    return _volume_type_access_query(context).\
        filter_by(volume_type_id=volume_type_id).all()


@require_admin_context
def volume_type_access_add(context, type_id, project_id):
    """Add given tenant to the volume type access list."""
    volume_type_id = _volume_type_get_id_from_volume_type(context, type_id)

    access_ref = models.VolumeTypeProjects()
    access_ref.update({"volume_type_id": volume_type_id,
                       "project_id": project_id})

    session = get_session()
    with session.begin():
        try:
            access_ref.save(session=session)
        except db_exc.DBDuplicateEntry:
            raise exception.VolumeTypeAccessExists(volume_type_id=type_id,
                                                   project_id=project_id)
        return access_ref


@require_admin_context
def volume_type_access_remove(context, type_id, project_id):
    """Remove given tenant from the volume type access list."""
    volume_type_id = _volume_type_get_id_from_volume_type(context, type_id)

    count = (_volume_type_access_query(context).
             filter_by(volume_type_id=volume_type_id).
             filter_by(project_id=project_id).
             update({'deleted': True,
                     'deleted_at': timeutils.utcnow(),
                     'updated_at': literal_column('updated_at')}))
    if count == 0:
        raise exception.VolumeTypeAccessNotFound(
            volume_type_id=type_id, project_id=project_id)


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
        for key, value in specs.items():
            try:
                spec_ref = _volume_type_extra_specs_get_item(
                    context, volume_type_id, key, session)
            except exception.VolumeTypeExtraSpecsNotFound:
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
            # 'QoS_Specs_Name' is an internal reserved key to store
            # the name of QoS specs
            root['key'] = 'QoS_Specs_Name'
            root['value'] = values['name']
            LOG.debug("DB qos_specs_create(): root %s", root)
            specs_root.update(root)
            specs_root.save(session=session)

            # Insert all specification entries for QoS specs
            for k, v in values['qos_specs'].items():
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
    # TODO(zhiteng) Add filters for 'consumer'

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
    """Make updates to an existing qos specs.

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
            except exception.QoSSpecsKeyNotFound:
                spec_ref = models.QualityOfServiceSpecs()
            id = None
            if spec_ref.get('id', None):
                id = spec_ref['id']
            else:
                id = str(uuid.uuid4())
            value = dict(id=id, key=key, value=specs[key],
                         specs_id=qos_specs_id,
                         deleted=False)
            LOG.debug('qos_specs_update() value: %s', value)
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
        if not encryption:
            raise exception.VolumeTypeEncryptionNotFound(
                type_id=volume_type_id)
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

        if 'encryption_id' not in values:
            values['encryption_id'] = six.text_type(uuid.uuid4())

        encryption.update(values)
        session.add(encryption)

        return encryption


@require_admin_context
def volume_type_encryption_update(context, volume_type_id, values):
    session = get_session()
    with session.begin():
        encryption = volume_type_encryption_get(context, volume_type_id,
                                                session)

        if not encryption:
            raise exception.VolumeTypeEncryptionNotFound(
                type_id=volume_type_id)

        encryption.update(values)

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
    """Return the encryption metadata for a given volume."""

    volume_ref = _volume_get(context, volume_id)
    encryption_ref = volume_type_encryption_get(context,
                                                volume_ref['volume_type_id'])

    values = {
        'encryption_key_id': volume_ref['encryption_key_id'],
    }

    if encryption_ref:
        for key in ['control_location', 'cipher', 'key_size', 'provider']:
            values[key] = encryption_ref[key]

    return values


####################


@require_context
def _volume_glance_metadata_get_all(context, session=None):
    query = model_query(context,
                        models.VolumeGlanceMetadata,
                        session=session)
    if is_user_context(context):
        query = query.filter(
            models.Volume.id == models.VolumeGlanceMetadata.volume_id,
            models.Volume.project_id == context.project_id)
    return query.all()


@require_context
def volume_glance_metadata_get_all(context):
    """Return the Glance metadata for all volumes."""

    return _volume_glance_metadata_get_all(context)


@require_context
def volume_glance_metadata_list_get(context, volume_id_list):
    """Return the glance metadata for a volume list."""
    query = model_query(context,
                        models.VolumeGlanceMetadata,
                        session=None)
    query = query.filter(
        models.VolumeGlanceMetadata.volume_id.in_(volume_id_list))
    return query.all()


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
        vol_glance_metadata.value = six.text_type(value)
        session.add(vol_glance_metadata)

    return


@require_context
@require_volume_exists
def volume_glance_metadata_bulk_create(context, volume_id, metadata):
    """Update the Glance metadata for a volume by adding new key:value pairs.

    This API does not support changing the value of a key once it has been
    created.
    """

    session = get_session()
    with session.begin():
        for (key, value) in metadata.items():
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
            vol_glance_metadata.value = six.text_type(value)
            session.add(vol_glance_metadata)


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
    """Update Glance metadata from a volume.

    Update the Glance metadata from a volume (created from a snapshot) by
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
def backup_get(context, backup_id, read_deleted=None, project_only=True):
    return _backup_get(context, backup_id)


def _backup_get(context, backup_id, session=None, read_deleted=None,
                project_only=True):
    result = model_query(context, models.Backup, session=session,
                         project_only=project_only,
                         read_deleted=read_deleted).\
        filter_by(id=backup_id).\
        first()

    if not result:
        raise exception.BackupNotFound(backup_id=backup_id)

    return result


def _backup_get_all(context, filters=None, marker=None, limit=None,
                    offset=None, sort_keys=None, sort_dirs=None):
    if filters and not is_valid_model_filters(models.Backup, filters):
        return []

    session = get_session()
    with session.begin():
        # Generate the paginate query
        query = _generate_paginate_query(context, session, marker,
                                         limit, sort_keys, sort_dirs, filters,
                                         offset, models.Backup)
        if query is None:
            return []
        return query.all()


def _backups_get_query(context, session=None, project_only=False):
    return model_query(context, models.Backup, session=session,
                       project_only=project_only)


def _process_backups_filters(query, filters):
    if filters:
        # Ensure that filters' keys exist on the model
        if not is_valid_model_filters(models.Backup, filters):
            return
        query = query.filter_by(**filters)
    return query


@require_admin_context
def backup_get_all(context, filters=None, marker=None, limit=None,
                   offset=None, sort_keys=None, sort_dirs=None):
    return _backup_get_all(context, filters, marker, limit, offset, sort_keys,
                           sort_dirs)


@require_admin_context
def backup_get_all_by_host(context, host):
    return model_query(context, models.Backup).filter_by(host=host).all()


@require_context
def backup_get_all_by_project(context, project_id, filters=None, marker=None,
                              limit=None, offset=None, sort_keys=None,
                              sort_dirs=None):

    authorize_project_context(context, project_id)
    if not filters:
        filters = {}
    else:
        filters = filters.copy()

    filters['project_id'] = project_id

    return _backup_get_all(context, filters, marker, limit, offset, sort_keys,
                           sort_dirs)


@require_context
def backup_get_all_by_volume(context, volume_id, filters=None):

    authorize_project_context(context, volume_id)
    if not filters:
        filters = {}
    else:
        filters = filters.copy()

    filters['volume_id'] = volume_id

    return _backup_get_all(context, filters)


@require_context
def backup_create(context, values):
    backup = models.Backup()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())
    backup.update(values)

    session = get_session()
    with session.begin():
        backup.save(session)
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
        transfer = models.Transfer()
        transfer.update(values)
        session.add(transfer)
        volume_ref.update(volume_ref)

    return transfer


@require_context
@_retry_on_deadlock
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
            LOG.error(_LE('Volume in unexpected state %s, expected '
                          'awaiting-transfer'), volume_ref['status'])
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

        session.query(models.Transfer).\
            filter_by(id=transfer_ref['id']).\
            update({'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})


###############################


@require_admin_context
def _consistencygroup_data_get_for_project(context, project_id,
                                           session=None):
    query = model_query(context,
                        func.count(models.ConsistencyGroup.id),
                        read_deleted="no",
                        session=session).\
        filter_by(project_id=project_id)

    result = query.first()

    return (0, result[0] or 0)


@require_admin_context
def consistencygroup_data_get_for_project(context, project_id):
    return _consistencygroup_data_get_for_project(context, project_id)


@require_context
def _consistencygroup_get(context, consistencygroup_id, session=None):
    result = model_query(context, models.ConsistencyGroup, session=session,
                         project_only=True).\
        filter_by(id=consistencygroup_id).\
        first()

    if not result:
        raise exception.ConsistencyGroupNotFound(
            consistencygroup_id=consistencygroup_id)

    return result


@require_context
def consistencygroup_get(context, consistencygroup_id):
    return _consistencygroup_get(context, consistencygroup_id)


@require_admin_context
def consistencygroup_get_all(context):
    return model_query(context, models.ConsistencyGroup).all()


@require_context
def consistencygroup_get_all_by_project(context, project_id):
    authorize_project_context(context, project_id)

    return model_query(context, models.ConsistencyGroup).\
        filter_by(project_id=project_id).all()


@require_context
def consistencygroup_create(context, values):
    consistencygroup = models.ConsistencyGroup()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())

    session = get_session()
    with session.begin():
        consistencygroup.update(values)
        session.add(consistencygroup)

        return _consistencygroup_get(context, values['id'], session=session)


@require_context
def consistencygroup_update(context, consistencygroup_id, values):
    session = get_session()
    with session.begin():
        result = model_query(context, models.ConsistencyGroup,
                             project_only=True).\
            filter_by(id=consistencygroup_id).\
            first()

        if not result:
            raise exception.ConsistencyGroupNotFound(
                _("No consistency group with id %s") % consistencygroup_id)

        result.update(values)
        result.save(session=session)
    return result


@require_admin_context
def consistencygroup_destroy(context, consistencygroup_id):
    session = get_session()
    with session.begin():
        model_query(context, models.ConsistencyGroup, session=session).\
            filter_by(id=consistencygroup_id).\
            update({'status': 'deleted',
                    'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})


###############################


@require_context
def _cgsnapshot_get(context, cgsnapshot_id, session=None):
    result = model_query(context, models.Cgsnapshot, session=session,
                         project_only=True).\
        filter_by(id=cgsnapshot_id).\
        first()

    if not result:
        raise exception.CgSnapshotNotFound(cgsnapshot_id=cgsnapshot_id)

    return result


@require_context
def cgsnapshot_get(context, cgsnapshot_id):
    return _cgsnapshot_get(context, cgsnapshot_id)


def is_valid_model_filters(model, filters):
    """Return True if filter values exist on the model

    :param model: a Cinder model
    :param filters: dictionary of filters
    """
    for key in filters.keys():
        try:
            getattr(model, key)
        except AttributeError:
            LOG.debug("'%s' filter key is not valid.", key)
            return False
    return True


def _cgsnapshot_get_all(context, project_id=None, group_id=None, filters=None):
    query = model_query(context, models.Cgsnapshot)

    if filters:
        if not is_valid_model_filters(models.Cgsnapshot, filters):
            return []
        query = query.filter_by(**filters)

    if project_id:
        query = query.filter_by(project_id=project_id)

    if group_id:
        query = query.filter_by(consistencygroup_id=group_id)

    return query.all()


@require_admin_context
def cgsnapshot_get_all(context, filters=None):
    return _cgsnapshot_get_all(context, filters=filters)


@require_admin_context
def cgsnapshot_get_all_by_group(context, group_id, filters=None):
    return _cgsnapshot_get_all(context, group_id=group_id, filters=filters)


@require_context
def cgsnapshot_get_all_by_project(context, project_id, filters=None):
    authorize_project_context(context, project_id)
    return _cgsnapshot_get_all(context, project_id=project_id, filters=filters)


@require_context
def cgsnapshot_create(context, values):
    cgsnapshot = models.Cgsnapshot()
    if not values.get('id'):
        values['id'] = str(uuid.uuid4())

    session = get_session()
    with session.begin():
        cgsnapshot.update(values)
        session.add(cgsnapshot)

        return _cgsnapshot_get(context, values['id'], session=session)


@require_context
def cgsnapshot_update(context, cgsnapshot_id, values):
    session = get_session()
    with session.begin():
        result = model_query(context, models.Cgsnapshot, project_only=True).\
            filter_by(id=cgsnapshot_id).\
            first()

        if not result:
            raise exception.CgSnapshotNotFound(
                _("No cgsnapshot with id %s") % cgsnapshot_id)

        result.update(values)
        result.save(session=session)
    return result


@require_admin_context
def cgsnapshot_destroy(context, cgsnapshot_id):
    session = get_session()
    with session.begin():
        model_query(context, models.Cgsnapshot, session=session).\
            filter_by(id=cgsnapshot_id).\
            update({'status': 'deleted',
                    'deleted': True,
                    'deleted_at': timeutils.utcnow(),
                    'updated_at': literal_column('updated_at')})


@require_admin_context
def purge_deleted_rows(context, age_in_days):
    """Purge deleted rows older than age from cinder tables."""
    try:
        age_in_days = int(age_in_days)
    except ValueError:
        msg = _('Invalid value for age, %(age)s') % {'age': age_in_days}
        LOG.exception(msg)
        raise exception.InvalidParameterValue(msg)
    if age_in_days <= 0:
        msg = _('Must supply a positive value for age')
        LOG.error(msg)
        raise exception.InvalidParameterValue(msg)

    engine = get_engine()
    session = get_session()
    metadata = MetaData()
    metadata.bind = engine
    tables = []

    for model_class in models.__dict__.values():
        if hasattr(model_class, "__tablename__") \
                and hasattr(model_class, "deleted"):
            tables.append(model_class.__tablename__)

    # Reorder the list so the volumes table is last to avoid FK constraints
    tables.remove("volumes")
    tables.append("volumes")
    for table in tables:
        t = Table(table, metadata, autoload=True)
        LOG.info(_LI('Purging deleted rows older than age=%(age)d days '
                     'from table=%(table)s'), {'age': age_in_days,
                                               'table': table})
        deleted_age = timeutils.utcnow() - dt.timedelta(days=age_in_days)
        try:
            with session.begin():
                result = session.execute(
                    t.delete()
                    .where(t.c.deleted_at < deleted_age))
        except db_exc.DBReferenceError:
            LOG.exception(_LE('DBError detected when purging from '
                              'table=%(table)s'), {'table': table})
            raise

        rows_purged = result.rowcount
        LOG.info(_LI("Deleted %(row)d rows from table=%(table)s"),
                 {'row': rows_purged, 'table': table})


###############################


@require_context
def driver_initiator_data_update(context, initiator, namespace, updates):
    session = get_session()
    with session.begin():
        set_values = updates.get('set_values', {})
        for key, value in set_values.items():
            data = session.query(models.DriverInitiatorData).\
                filter_by(initiator=initiator).\
                filter_by(namespace=namespace).\
                filter_by(key=key).\
                first()

            if data:
                data.update({'value': value})
                data.save(session=session)
            else:
                data = models.DriverInitiatorData()
                data.initiator = initiator
                data.namespace = namespace
                data.key = key
                data.value = value
                session.add(data)

        remove_values = updates.get('remove_values', [])
        for key in remove_values:
            session.query(models.DriverInitiatorData).\
                filter_by(initiator=initiator).\
                filter_by(namespace=namespace).\
                filter_by(key=key).\
                delete()


@require_context
def driver_initiator_data_get(context, initiator, namespace):
    session = get_session()
    with session.begin():
        return session.query(models.DriverInitiatorData).\
            filter_by(initiator=initiator).\
            filter_by(namespace=namespace).\
            all()


###############################


PAGINATION_HELPERS = {
    models.Volume: (_volume_get_query, _process_volume_filters, _volume_get),
    models.Snapshot: (_snaps_get_query, _process_snaps_filters, _snapshot_get),
    models.Backup: (_backups_get_query, _process_backups_filters, _backup_get)
}


###############################


@require_context
def image_volume_cache_create(context, host, image_id, image_updated_at,
                              volume_id, size):
    session = get_session()
    with session.begin():
        cache_entry = models.ImageVolumeCacheEntry()
        cache_entry.host = host
        cache_entry.image_id = image_id
        cache_entry.image_updated_at = image_updated_at
        cache_entry.volume_id = volume_id
        cache_entry.size = size
        session.add(cache_entry)
        return cache_entry


@require_context
def image_volume_cache_delete(context, volume_id):
    session = get_session()
    with session.begin():
        session.query(models.ImageVolumeCacheEntry).\
            filter_by(volume_id=volume_id).\
            delete()


@require_context
def image_volume_cache_get_and_update_last_used(context, image_id, host):
    session = get_session()
    with session.begin():
        entry = session.query(models.ImageVolumeCacheEntry).\
            filter_by(image_id=image_id).\
            filter_by(host=host).\
            order_by(desc(models.ImageVolumeCacheEntry.last_used)).\
            first()

        if entry:
            entry.last_used = timeutils.utcnow()
            entry.save(session=session)
        return entry


@require_context
def image_volume_cache_get_by_volume_id(context, volume_id):
    session = get_session()
    with session.begin():
        return session.query(models.ImageVolumeCacheEntry).\
            filter_by(volume_id=volume_id).\
            first()


@require_context
def image_volume_cache_get_all_for_host(context, host):
    session = get_session()
    with session.begin():
        return session.query(models.ImageVolumeCacheEntry).\
            filter_by(host=host).\
            order_by(desc(models.ImageVolumeCacheEntry.last_used)).\
            all()
