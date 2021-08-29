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

"""The volumes V3 api."""
from http import HTTPStatus

from oslo_log import log as logging
from oslo_log import versionutils
from oslo_utils import timeutils
import webob
from webob import exc

from cinder.api import api_utils
from cinder.api import common
from cinder.api.contrib import scheduler_hints
from cinder.api import microversions as mv
from cinder.api.openstack import wsgi
from cinder.api.schemas import volumes
from cinder.api.v2 import volumes as volumes_v2
from cinder.api.v3.views import volumes as volume_views_v3
from cinder.api import validation
from cinder.backup import api as backup_api
from cinder import exception
from cinder import group as group_api
from cinder.i18n import _
from cinder.image import glance
from cinder import objects
from cinder.policies import volumes as policy
from cinder import utils

LOG = logging.getLogger(__name__)


class VolumeController(volumes_v2.VolumeController):
    """The Volumes API controller for the OpenStack API V3."""

    _view_builder_class = volume_views_v3.ViewBuilder

    def __init__(self, ext_mgr):
        self.group_api = group_api.API()
        self.backup_api = backup_api.API()
        super(VolumeController, self).__init__(ext_mgr)

    def delete(self, req, id):
        """Delete a volume."""
        context = req.environ['cinder.context']
        req_version = req.api_version_request

        cascade = utils.get_bool_param('cascade', req.params)
        force = False

        params = ""
        if req_version.matches(mv.VOLUME_DELETE_FORCE):
            force = utils.get_bool_param('force', req.params)
            if cascade or force:
                params = "(cascade: %(c)s, force: %(f)s)" % {'c': cascade,
                                                             'f': force}

        LOG.info("Delete volume with id: %(id)s %(params)s",
                 {'id': id, 'params': params}, context=context)

        volume = self.volume_api.get(context, id)

        if force:
            context.authorize(policy.FORCE_DELETE_POLICY, target_obj=volume)

        self.volume_api.delete(context, volume,
                               cascade=cascade,
                               force=force)

        return webob.Response(status_int=HTTPStatus.ACCEPTED)

    MV_ADDED_FILTERS = (
        (mv.get_prior_version(mv.VOLUME_LIST_GLANCE_METADATA),
         'glance_metadata'),
        (mv.get_prior_version(mv.VOLUME_LIST_GROUP), 'group_id'),
        (mv.get_prior_version(mv.VOLUME_TIME_COMPARISON_FILTER), 'created_at'),
        (mv.get_prior_version(mv.VOLUME_TIME_COMPARISON_FILTER), 'updated_at'),
        # REST API receives consumes_quota, but process_general_filtering
        # transforms it into use_quota
        (mv.get_prior_version(mv.USE_QUOTA), 'use_quota'),
    )

    @common.process_general_filtering('volume')
    def _process_volume_filtering(self, context=None, filters=None,
                                  req_version=None):
        for version, field in self.MV_ADDED_FILTERS:
            if req_version.matches(None, version):
                filters.pop(field, None)

        api_utils.remove_invalid_filter_options(
            context, filters,
            self._get_volume_filter_options())

    def _handle_time_comparison_filters(self, filters):
        for time_comparison_filter in ['created_at', 'updated_at']:
            if time_comparison_filter in filters:
                time_filter_dict = {}
                comparison_units = filters[time_comparison_filter].split(',')
                operators = common.get_time_comparsion_operators()
                for comparison_unit in comparison_units:
                    try:
                        operator_and_time = comparison_unit.split(":")
                        comparison_operator = operator_and_time[0]
                        time = ''
                        for time_str in operator_and_time[1:-1]:
                            time += time_str + ":"
                        time += operator_and_time[-1]
                        if comparison_operator not in operators:
                            msg = _(
                                'Invalid %s operator') % comparison_operator
                            raise exc.HTTPBadRequest(explanation=msg)
                    except IndexError:
                        msg = _('Invalid %s value') % time_comparison_filter
                        raise exc.HTTPBadRequest(explanation=msg)
                    try:
                        parsed_time = timeutils.parse_isotime(time)
                    except ValueError:
                        msg = _('Invalid %s value') % time
                        raise exc.HTTPBadRequest(explanation=msg)
                    time_filter_dict[comparison_operator] = parsed_time

                filters[time_comparison_filter] = time_filter_dict

    def _get_volumes(self, req, is_detail):
        """Returns a list of volumes, transformed through view builder."""

        context = req.environ['cinder.context']
        req_version = req.api_version_request

        params = req.params.copy()
        marker, limit, offset = common.get_pagination_params(params)
        sort_keys, sort_dirs = common.get_sort_params(params)
        filters = params

        show_count = False
        if req_version.matches(
                mv.SUPPORT_COUNT_INFO) and 'with_count' in filters:
            show_count = utils.get_bool_param('with_count', filters)
            filters.pop('with_count')

        self._process_volume_filtering(context=context, filters=filters,
                                       req_version=req_version)

        # NOTE: it's 'name' in the REST API, but 'display_name' in the
        # database layer, so we need to do this translation
        if 'name' in sort_keys:
            sort_keys[sort_keys.index('name')] = 'display_name'

        if 'name' in filters:
            filters['display_name'] = filters.pop('name')

        if 'use_quota' in filters:
            filters['use_quota'] = utils.get_bool_param('use_quota', filters)

        self._handle_time_comparison_filters(filters)

        strict = req.api_version_request.matches(
            mv.VOLUME_LIST_BOOTABLE, None)
        self.volume_api.check_volume_filters(filters, strict)

        volumes = self.volume_api.get_all(context, marker, limit,
                                          sort_keys=sort_keys,
                                          sort_dirs=sort_dirs,
                                          filters=filters.copy(),
                                          viewable_admin_meta=True,
                                          offset=offset)
        total_count = None
        if show_count:
            total_count = self.volume_api.calculate_resource_count(
                context, 'volume', filters)

        for volume in volumes:
            api_utils.add_visible_admin_metadata(volume)

        req.cache_db_volumes(volumes.objects)

        if is_detail:
            volumes = self._view_builder.detail_list(
                req, volumes, total_count)
        else:
            volumes = self._view_builder.summary_list(
                req, volumes, total_count)
        return volumes

    @wsgi.Controller.api_version(mv.VOLUME_SUMMARY)
    def summary(self, req):
        """Return summary of volumes."""
        view_builder_v3 = volume_views_v3.ViewBuilder()
        context = req.environ['cinder.context']
        filters = req.params.copy()

        api_utils.remove_invalid_filter_options(
            context,
            filters,
            self._get_volume_filter_options())

        num_vols, sum_size, metadata = self.volume_api.get_volume_summary(
            context, filters=filters)

        req_version = req.api_version_request
        if req_version.matches(mv.VOLUME_SUMMARY_METADATA):
            all_distinct_metadata = metadata
        else:
            all_distinct_metadata = None

        return view_builder_v3.quick_summary(num_vols, int(sum_size),
                                             all_distinct_metadata)

    @wsgi.response(HTTPStatus.ACCEPTED)
    @wsgi.Controller.api_version(mv.VOLUME_REVERT)
    @wsgi.action('revert')
    def revert(self, req, id, body):
        """revert a volume to a snapshot"""

        context = req.environ['cinder.context']
        self.assert_valid_body(body, 'revert')
        snapshot_id = body['revert'].get('snapshot_id')
        volume = self.volume_api.get_volume(context, id)
        try:
            l_snap = volume.get_latest_snapshot()
        except exception.VolumeSnapshotNotFound:
            msg = _("Volume %s doesn't have any snapshots.")
            raise exc.HTTPBadRequest(explanation=msg % volume.id)
        # Ensure volume and snapshot match.
        if snapshot_id is None or snapshot_id != l_snap.id:
            msg = _("Specified snapshot %(s_id)s is None or not "
                    "the latest one of volume %(v_id)s.")
            raise exc.HTTPBadRequest(explanation=msg % {'s_id': snapshot_id,
                                                        'v_id': volume.id})
        if volume.size != l_snap.volume_size:
            msg = _("Can't revert volume %(v_id)s to its latest snapshot "
                    "%(s_id)s. The volume size must be equal to the snapshot "
                    "size.")
            raise exc.HTTPBadRequest(explanation=msg % {'s_id': snapshot_id,
                                                        'v_id': volume.id})
        try:
            msg = 'Reverting volume %(v_id)s to snapshot %(s_id)s.'
            LOG.info(msg, {'v_id': volume.id,
                           's_id': l_snap.id})
            self.volume_api.revert_to_snapshot(context, volume, l_snap)
        except (exception.InvalidVolume, exception.InvalidSnapshot) as e:
            raise exc.HTTPConflict(explanation=str(e))

    def _get_image_snapshot(self, context, image_uuid):
        image_snapshot = None
        if image_uuid:
            image_service = glance.get_default_image_service()
            image_meta = image_service.show(context, image_uuid)
            if image_meta is not None:
                bdms = image_meta.get('properties', {}).get(
                    'block_device_mapping', [])
                if bdms:
                    boot_bdm = [bdm for bdm in bdms if (
                        bdm.get('source_type') == 'snapshot' and
                        bdm.get('boot_index') == 0)]
                    if boot_bdm:
                        try:
                            image_snapshot = self.volume_api.get_snapshot(
                                context, boot_bdm[0].get('snapshot_id'))
                            return image_snapshot
                        except exception.NotFound:
                            explanation = _(
                                'Nova specific image is found, but boot '
                                'volume snapshot id:%s not found.'
                            ) % boot_bdm[0].get('snapshot_id')
                            raise exc.HTTPNotFound(explanation=explanation)
            return image_snapshot

    @wsgi.response(HTTPStatus.ACCEPTED)
    @validation.schema(volumes.create, mv.BASE_VERSION,
                       mv.get_prior_version(mv.GROUP_VOLUME))
    @validation.schema(volumes.create_volume_v313, mv.GROUP_VOLUME,
                       mv.get_prior_version(mv.VOLUME_CREATE_FROM_BACKUP))
    @validation.schema(volumes.create_volume_v347,
                       mv.VOLUME_CREATE_FROM_BACKUP,
                       mv.get_prior_version(mv.SUPPORT_VOLUME_SCHEMA_CHANGES))
    @validation.schema(volumes.create_volume_v353,
                       mv.SUPPORT_VOLUME_SCHEMA_CHANGES)
    def create(self, req, body):
        """Creates a new volume.

        :param req: the request
        :param body: the request body
        :returns: dict -- the new volume dictionary
        :raises HTTPNotFound, HTTPBadRequest:
        """
        LOG.debug('Create volume request body: %s', body)
        context = req.environ['cinder.context']

        req_version = req.api_version_request

        # NOTE (pooja_jadhav) To fix bug 1774155, scheduler hints is not
        # loaded as a standard extension. If user passes
        # OS-SCH-HNT:scheduler_hints in the request body, then it will be
        # validated in the create method and this method will add
        # scheduler_hints in body['volume'].
        body = scheduler_hints.create(req, body)

        volume = body['volume']
        kwargs = {}
        self.validate_name_and_description(volume, check_length=False)

        # NOTE: it's 'name'/'description' in the REST API, but
        # 'display_name'/display_description' in the database layer,
        # so we need to do this translation
        if 'name' in volume:
            volume['display_name'] = volume.pop('name')
        if 'description' in volume:
            volume['display_description'] = volume.pop('description')

        if 'image_id' in volume:
            volume['imageRef'] = volume.pop('image_id')

        req_volume_type = volume.get('volume_type', None)
        if req_volume_type:
            # Not found exception will be handled at the wsgi level
            kwargs['volume_type'] = (
                objects.VolumeType.get_by_name_or_id(context, req_volume_type))

        kwargs['metadata'] = volume.get('metadata', None)

        snapshot_id = volume.get('snapshot_id')
        if snapshot_id is not None:
            # Not found exception will be handled at the wsgi level
            kwargs['snapshot'] = self.volume_api.get_snapshot(context,
                                                              snapshot_id)
        else:
            kwargs['snapshot'] = None

        source_volid = volume.get('source_volid')
        if source_volid is not None:
            # Not found exception will be handled at the wsgi level
            kwargs['source_volume'] = (
                self.volume_api.get_volume(context,
                                           source_volid))
        else:
            kwargs['source_volume'] = None

        kwargs['group'] = None
        kwargs['consistencygroup'] = None
        consistencygroup_id = volume.get('consistencygroup_id')
        if consistencygroup_id is not None:
            # Not found exception will be handled at the wsgi level
            kwargs['group'] = self.group_api.get(context, consistencygroup_id)

        # Get group_id if volume is in a group.
        group_id = volume.get('group_id')
        if group_id is not None:
            # Not found exception will be handled at the wsgi level
            kwargs['group'] = self.group_api.get(context, group_id)

        image_ref = volume.get('imageRef')
        if image_ref is not None:
            image_uuid = self._image_uuid_from_ref(image_ref, context)
            image_snapshot = self._get_image_snapshot(context, image_uuid)
            if (req_version.matches(mv.get_api_version(
                    mv.SUPPORT_NOVA_IMAGE)) and image_snapshot):
                kwargs['snapshot'] = image_snapshot
            else:
                kwargs['image_id'] = image_uuid

        backup_id = volume.get('backup_id')
        if backup_id:
            kwargs['backup'] = self.backup_api.get(context,
                                                   backup_id=backup_id)

        size = volume.get('size', None)
        if size is None and kwargs['snapshot'] is not None:
            size = kwargs['snapshot']['volume_size']
        elif size is None and kwargs['source_volume'] is not None:
            size = kwargs['source_volume']['size']
        elif size is None and kwargs.get('backup') is not None:
            size = kwargs['backup']['size']

        LOG.info("Create volume of %s GB", size)

        kwargs['availability_zone'] = volume.get('availability_zone', None)
        kwargs['scheduler_hints'] = volume.get('scheduler_hints', None)
        multiattach = volume.get('multiattach', False)
        kwargs['multiattach'] = multiattach

        if multiattach:
            msg = ("The option 'multiattach' "
                   "is deprecated and will be removed in a future "
                   "release.  The default behavior going forward will "
                   "be to specify multiattach enabled volume types.")
            versionutils.report_deprecated_feature(LOG, msg)
        try:
            new_volume = self.volume_api.create(
                context, size, volume.get('display_name'),
                volume.get('display_description'), **kwargs)
        except exception.VolumeTypeDefaultMisconfiguredError as err:
            raise exc.HTTPInternalServerError(explanation=err.msg)

        retval = self._view_builder.detail(req, new_volume)
        return retval


def create_resource(ext_mgr):
    return wsgi.Resource(VolumeController(ext_mgr))
