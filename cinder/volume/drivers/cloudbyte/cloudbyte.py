# Copyright 2015 CloudByte Inc.
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

import httplib
import json
import time
import urllib

from oslo_log import log as logging
from oslo_utils import units
import six

from cinder import exception
from cinder.i18n import _, _LE, _LI
from cinder.openstack.common import loopingcall
from cinder.volume.drivers.cloudbyte import options
from cinder.volume.drivers.san import san

LOG = logging.getLogger(__name__)


class CloudByteISCSIDriver(san.SanISCSIDriver):
    """CloudByte ISCSI Driver.

    Version history:
        1.0.0 - Initial driver
    """

    VERSION = '1.0.0'
    volume_stats = {}

    def __init__(self, *args, **kwargs):
        super(CloudByteISCSIDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(
            options.cloudbyte_add_qosgroup_opts)
        self.configuration.append_config_values(
            options.cloudbyte_create_volume_opts)
        self.configuration.append_config_values(
            options.cloudbyte_connection_opts)
        self.get_volume_stats()

    def _get_url(self, cmd, params, apikey):
        """Will prepare URL that connects to CloudByte."""

        if params is None:
            params = {}

        params['command'] = cmd
        params['response'] = 'json'

        sanitized_params = {}

        for key in params:
            value = params[key]
            if value is not None:
                sanitized_params[key] = six.text_type(value)

        sanitized_params = urllib.urlencode(sanitized_params)
        url = ('/client/api?%s' % sanitized_params)

        LOG.debug("CloudByte URL to be executed: [%s].", url)

        # Add the apikey
        api = {}
        api['apiKey'] = apikey
        url = url + '&' + urllib.urlencode(api)

        return url

    def _extract_http_error(self, error_data):
        # Extract the error message from error_data
        error_msg = ""

        # error_data is a single key value dict
        for key, value in error_data.iteritems():
            error_msg = value.get('errortext')

        return error_msg

    def _execute_and_get_response_details(self, host, url):
        """Will prepare response after executing an http request."""

        res_details = {}
        try:
            # Prepare the connection
            connection = httplib.HTTPSConnection(host)
            # Make the connection
            connection.request('GET', url)
            # Extract the response as the connection was successful
            response = connection.getresponse()
            # Read the response
            data = response.read()
            # Transform the json string into a py object
            data = json.loads(data)
            # Extract http error msg if any
            error_details = None
            if response.status != 200:
                error_details = self._extract_http_error(data)

            # Prepare the return object
            res_details['data'] = data
            res_details['error'] = error_details
            res_details['http_status'] = response.status

        finally:
            connection.close()
            LOG.debug("CloudByte connection was closed successfully.")

        return res_details

    def _api_request_for_cloudbyte(self, cmd, params, version=None):
        """Make http calls to CloudByte."""
        LOG.debug("Executing CloudByte API for command [%s].", cmd)

        if version is None:
            version = CloudByteISCSIDriver.VERSION

        # Below is retrieved from /etc/cinder/cinder.conf
        apikey = self.configuration.cb_apikey

        if apikey is None:
            msg = (_("API key is missing for CloudByte driver."))
            raise exception.VolumeBackendAPIException(data=msg)

        host = self.configuration.san_ip

        # Construct the CloudByte URL with query params
        url = self._get_url(cmd, params, apikey)

        data = {}
        error_details = None
        http_status = None

        try:
            # Execute CloudByte API & frame the response
            res_obj = self._execute_and_get_response_details(host, url)

            data = res_obj['data']
            error_details = res_obj['error']
            http_status = res_obj['http_status']

        except httplib.HTTPException as ex:
            msg = (_("Error executing CloudByte API [%(cmd)s], "
                     "Error: %(err)s.") %
                   {'cmd': cmd, 'err': ex})
            raise exception.VolumeBackendAPIException(data=msg)

        # Check if it was an error response from CloudByte
        if http_status != 200:
            msg = (_("Failed to execute CloudByte API [%(cmd)s]."
                     " Http status: %(status)s,"
                     " Error: %(error)s.") %
                   {'cmd': cmd, 'status': http_status,
                    'error': error_details})
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.info(_LI("CloudByte API executed successfully for command [%s]."),
                 cmd)

        return data

    def _request_tsm_details(self, account_id):
        params = {"accountid": account_id}

        # List all CloudByte tsm
        data = self._api_request_for_cloudbyte("listTsm", params)
        return data

    def _override_params(self, default_dict, filtered_user_dict):
        """Override the default config values with user provided values.
        """

        if filtered_user_dict is None:
            # Nothing to override
            return default_dict

        for key, value in default_dict.iteritems():
            # Fill the user dict with default options based on condition
            if filtered_user_dict.get(key) is None and value is not None:
                filtered_user_dict[key] = value

        return filtered_user_dict

    def _add_qos_group_request(self, volume, tsmid, volume_name):
        # Get qos related params from configuration
        params = self.configuration.cb_add_qosgroup

        if params is None:
            params = {}

        params['name'] = "QoS_" + volume_name
        params['tsmid'] = tsmid

        data = self._api_request_for_cloudbyte("addQosGroup", params)
        return data

    def _create_volume_request(self, volume, datasetid, qosgroupid,
                               tsmid, volume_name):

        size = volume.get('size')
        quotasize = six.text_type(size) + "G"

        # Prepare the user input params
        params = {
            "datasetid": datasetid,
            "name": volume_name,
            "qosgroupid": qosgroupid,
            "tsmid": tsmid,
            "quotasize": quotasize
        }

        # Get the additional params from configuration
        params = self._override_params(self.configuration.cb_create_volume,
                                       params)

        data = self._api_request_for_cloudbyte("createVolume", params)
        return data

    def _queryAsyncJobResult_request(self, jobid):
        async_cmd = "queryAsyncJobResult"
        params = {
            "jobId": jobid,
        }
        data = self._api_request_for_cloudbyte(async_cmd, params)
        return data

    def _get_tsm_details(self, data, tsm_name):
        # Filter required tsm's details
        tsms = data['listTsmResponse']['listTsm']
        tsmdetails = {}
        for tsm in tsms:
            if tsm['name'] == tsm_name:
                tsmdetails['datasetid'] = tsm['datasetid']
                tsmdetails['tsmid'] = tsm['id']
                break

        return tsmdetails

    def _wait_for_volume_creation(self, volume_response, cb_volume_name):
        """Given the job wait for it to complete."""

        vol_res = volume_response.get('createvolumeresponse')

        if vol_res is None:
            msg = _("Null response received while creating volume [%s] "
                    "at CloudByte storage.") % cb_volume_name
            raise exception.VolumeBackendAPIException(data=msg)

        jobid = vol_res.get('jobid')

        if jobid is None:
            msg = _("Jobid not found in CloudByte's "
                    "create volume [%s] response.") % cb_volume_name
            raise exception.VolumeBackendAPIException(data=msg)

        def _retry_check_for_volume_creation():
            """Called at an interval till the volume is created."""

            retries = kwargs['retries']
            max_retries = kwargs['max_retries']
            jobid = kwargs['jobid']
            cb_vol = kwargs['cb_vol']

            # Query the CloudByte storage with this jobid
            volume_response = self._queryAsyncJobResult_request(jobid)

            result_res = None
            if volume_response is not None:
                result_res = volume_response.get('queryasyncjobresultresponse')

            if volume_response is None or result_res is None:
                msg = _(
                    "Null response received while querying "
                    "for create volume job [%s] "
                    "at CloudByte storage.") % jobid
                raise exception.VolumeBackendAPIException(data=msg)

            status = result_res.get('jobstatus')

            if status == 1:
                LOG.info(_LI("Volume [%s] created successfully in "
                             "CloudByte storage."), cb_vol)
                raise loopingcall.LoopingCallDone()

            elif retries == max_retries:
                # All attempts exhausted
                LOG.error(_LE("Error in creating volume [%(vol)s] in "
                              "CloudByte storage. "
                              "Exhausted all [%(max)s] attempts."),
                          {'vol': cb_vol, 'max': retries})
                raise loopingcall.LoopingCallDone(retvalue=False)

            else:
                retries += 1
                kwargs['retries'] = retries
                LOG.debug("Wait for volume [%(vol)s] creation, "
                          "retry [%(retry)s] of [%(max)s].",
                          {'vol': cb_vol,
                           'retry': retries,
                           'max': max_retries})

        retry_interval = (
            self.configuration.cb_confirm_volume_create_retry_interval)

        max_retries = (
            self.configuration.cb_confirm_volume_create_retries)

        kwargs = {'retries': 0,
                  'max_retries': max_retries,
                  'jobid': jobid,
                  'cb_vol': cb_volume_name}

        timer = loopingcall.FixedIntervalLoopingCall(
            _retry_check_for_volume_creation)
        timer.start(interval=retry_interval).wait()

    def _get_volume_id_from_response(self, cb_volumes, volume_name):
        """Search the volume in CloudByte storage."""

        vol_res = cb_volumes.get('listFilesystemResponse')

        if vol_res is None:
            msg = _("Null response received from CloudByte's "
                    "list filesystem.")
            raise exception.VolumeBackendAPIException(data=msg)

        volumes = vol_res.get('filesystem')

        if volumes is None:
            msg = _('No volumes found in CloudByte storage.')
            raise exception.VolumeBackendAPIException(data=msg)

        volume_id = None

        for vol in volumes:
            if vol['name'] == volume_name:
                volume_id = vol['id']
                break

        if volume_id is None:
            msg = _("Volume [%s] not found in CloudByte "
                    "storage.") % volume_name
            raise exception.VolumeBackendAPIException(data=msg)

        return volume_id

    def _get_qosgroupid_id_from_response(self, cb_volumes, volume_id):
        volumes = cb_volumes['listFilesystemResponse']['filesystem']
        qosgroup_id = None

        for vol in volumes:
            if vol['id'] == volume_id:
                qosgroup_id = vol['groupid']
                break

        return qosgroup_id

    def _build_provider_details_from_volume(self, volume):
        model_update = {}

        model_update['provider_location'] = (
            '%s %s %s' % (volume['ipaddress'] + ':3260', volume['iqnname'], 0)
        )

        # Will provide CHAP Authentication on forthcoming patches/release
        model_update['provider_auth'] = None

        model_update['provider_id'] = volume['id']

        LOG.debug("CloudByte volume [%(vol)s] properties: [%(props)s].",
                  {'vol': volume['iqnname'], 'props': model_update})

        return model_update

    def _build_provider_details_from_response(self, cb_volumes, volume_name):
        """Get provider information."""

        model_update = {}
        volumes = cb_volumes['listFilesystemResponse']['filesystem']

        for vol in volumes:
            if vol['name'] == volume_name:
                model_update = self._build_provider_details_from_volume(vol)
                break

        return model_update

    def _get_initiator_group_id_from_response(self, data):
        """Find iSCSI initiator group id."""

        ig_list_res = data.get('listInitiatorsResponse')

        if ig_list_res is None:
            msg = _("Null response received from CloudByte's "
                    "list iscsi initiators.")
            raise exception.VolumeBackendAPIException(data=msg)

        ig_list = ig_list_res.get('initiator')

        if ig_list is None:
            msg = _('No iscsi initiators were found in CloudByte.')
            raise exception.VolumeBackendAPIException(data=msg)

        ig_id = None

        for ig in ig_list:
            if ig.get('initiatorgroup') == 'ALL':
                ig_id = ig['id']
                break

        return ig_id

    def _get_iscsi_service_id_from_response(self, volume_id, data):
        iscsi_service_res = data.get('listVolumeiSCSIServiceResponse')

        if iscsi_service_res is None:
            msg = _("Null response received from CloudByte's "
                    "list volume iscsi service.")
            raise exception.VolumeBackendAPIException(data=msg)

        iscsi_service_list = iscsi_service_res.get('iSCSIService')

        if iscsi_service_list is None:
            msg = _('No iscsi services found in CloudByte storage.')
            raise exception.VolumeBackendAPIException(data=msg)

        iscsi_id = None

        for iscsi_service in iscsi_service_list:
            if iscsi_service['volume_id'] == volume_id:
                iscsi_id = iscsi_service['id']
                break

        if iscsi_id is None:
            msg = _("No iscsi service found for CloudByte "
                    "volume [%s].") % volume_id
            raise exception.VolumeBackendAPIException(data=msg)
        else:
            return iscsi_id

    def _request_update_iscsi_service(self, iscsi_id, ig_id):
        params = {
            "id": iscsi_id,
            "igid": ig_id
        }

        self._api_request_for_cloudbyte(
            'updateVolumeiSCSIService', params)

    def _get_cb_snapshot_path(self, snapshot, volume_id):
        """Find CloudByte snapshot path."""

        params = {"id": volume_id}

        # List all snapshot from CloudByte
        cb_snapshots_list = self._api_request_for_cloudbyte(
            'listStorageSnapshots', params)

        # Filter required snapshot from list
        cb_snap_res = cb_snapshots_list.get('listDatasetSnapshotsResponse')

        cb_snapshot = {}
        if cb_snap_res is not None:
            cb_snapshot = cb_snap_res.get('snapshot')

        path = None

        # Filter snapshot path
        for snap in cb_snapshot:
            if snap['name'] == snapshot['display_name']:
                path = snap['path']
                break

        return path

    def _get_account_id_from_name(self, account_name):
        params = {}
        data = self._api_request_for_cloudbyte("listAccount", params)
        accounts = data["listAccountResponse"]["account"]

        account_id = None
        for account in accounts:
            if account.get("name") == account_name:
                account_id = account.get("id")
                break

        if account_id is None:
            msg = _("Failed to get CloudByte account details "
                    "for account [%s].") % account_name
            raise exception.VolumeBackendAPIException(data=msg)

        return account_id

    def _search_volume_id(self, cb_volumes, cb_volume_id):
        """Search the volume in CloudByte."""

        volumes_res = cb_volumes.get('listFilesystemResponse')

        if volumes_res is None:
            msg = _("No response was received from CloudByte's "
                    "list filesystem api call.")
            raise exception.VolumeBackendAPIException(data=msg)

        volumes = volumes_res.get('filesystem')

        if volumes is None:
            msg = _("No volume was found at CloudByte storage.")
            raise exception.VolumeBackendAPIException(data=msg)

        volume_id = None

        for vol in volumes:
            if vol['id'] == cb_volume_id:
                volume_id = vol['id']
                break

        return volume_id

    def _generate_clone_name(self):
        """Generates clone name when it is not provided."""

        clone_name = ("clone_" + time.strftime("%d%m%Y") +
                      time.strftime("%H%M%S"))
        return clone_name

    def _generate_snapshot_name(self):
        """Generates snapshot_name when it is not provided."""

        snapshot_name = ("snap_" + time.strftime("%d%m%Y") +
                         time.strftime("%H%M%S"))
        return snapshot_name

    def _get_storage_info(self, tsmname):
        """Get CloudByte TSM that is associated with OpenStack backend."""

        # List all TSMs from CloudByte storage
        tsm_list = self._api_request_for_cloudbyte('listTsm', params={})

        tsm_details_res = tsm_list.get('listTsmResponse')

        if tsm_details_res is None:
            msg = _("No response was received from CloudByte storage "
                    "list tsm API call.")
            raise exception.VolumeBackendAPIException(data=msg)

        tsm_details = tsm_details_res.get('listTsm')

        data = {}
        flag = 0
        # Filter required TSM and get storage info
        for tsms in tsm_details:
            if tsms['name'] == tsmname:
                flag = 1
                data['total_capacity_gb'] = (
                    float(tsms['numericquota']) / units.Ki)
                data['free_capacity_gb'] = (
                    float(tsms['availablequota']) / units.Ki)
                break

        # TSM not found in CloudByte storage
        if flag == 0:
            LOG.error(_LE("TSM [%s] not found in CloudByte storage."), tsmname)
            data['total_capacity_gb'] = 0.0
            data['free_capacity_gb'] = 0.0

        return data

    def create_volume(self, volume):

        tsm_name = self.configuration.cb_tsm_name
        account_name = self.configuration.cb_account_name

        # Get account id of this account
        account_id = self._get_account_id_from_name(account_name)

        # Set backend storage volume name using OpenStack volume id
        cb_volume_name = volume['id'].replace("-", "")

        LOG.debug("Will create a volume [%(cb_vol)s] in TSM [%(tsm)s] "
                  "at CloudByte storage w.r.t "
                  "OpenStack volume [%(stack_vol)s].",
                  {'cb_vol': cb_volume_name,
                   'stack_vol': volume.get('id'),
                   'tsm': tsm_name})

        tsm_data = self._request_tsm_details(account_id)
        tsm_details = self._get_tsm_details(tsm_data, tsm_name)

        # Send request to create a qos group before creating a volume
        LOG.debug("Creating qos group for CloudByte volume [%s].",
                  cb_volume_name)
        qos_data = self._add_qos_group_request(
            volume, tsm_details.get('tsmid'), cb_volume_name)

        # Extract the qos group id from response
        qosgroupid = qos_data['addqosgroupresponse']['qosgroup']['id']

        LOG.debug("Successfully created qos group for CloudByte volume [%s].",
                  cb_volume_name)

        # Send a create volume request to CloudByte API
        vol_data = self._create_volume_request(
            volume, tsm_details.get('datasetid'), qosgroupid,
            tsm_details.get('tsmid'), cb_volume_name)

        # Since create volume is an async call;
        # need to confirm the creation before proceeding further
        self._wait_for_volume_creation(vol_data, cb_volume_name)

        # Fetch iscsi id
        cb_volumes = self._api_request_for_cloudbyte(
            'listFileSystem', params={})
        volume_id = self._get_volume_id_from_response(cb_volumes,
                                                      cb_volume_name)

        params = {"storageid": volume_id}

        iscsi_service_data = self._api_request_for_cloudbyte(
            'listVolumeiSCSIService', params)
        iscsi_id = self._get_iscsi_service_id_from_response(
            volume_id, iscsi_service_data)

        # Fetch the initiator group ID
        params = {"accountid": account_id}

        iscsi_initiator_data = self._api_request_for_cloudbyte(
            'listiSCSIInitiator', params)
        ig_id = self._get_initiator_group_id_from_response(
            iscsi_initiator_data)

        LOG.debug("Updating iscsi service for CloudByte volume [%s].",
                  cb_volume_name)

        # Update the iscsi service with above fetched iscsi_id & ig_id
        self._request_update_iscsi_service(iscsi_id, ig_id)

        LOG.debug("CloudByte volume [%(vol)s] updated with "
                  "iscsi id [%(iscsi)s] and ig id [%(ig)s].",
                  {'vol': cb_volume_name, 'iscsi': iscsi_id, 'ig': ig_id})

        # Provide the model after successful completion of above steps
        provider = self._build_provider_details_from_response(
            cb_volumes, cb_volume_name)

        LOG.info(_LI("Successfully created a CloudByte volume [%(cb_vol)s] "
                 "w.r.t OpenStack volume [%(stack_vol)s]."),
                 {'cb_vol': cb_volume_name, 'stack_vol': volume.get('id')})

        return provider

    def delete_volume(self, volume):

        params = {}

        # OpenStack  source volume id
        source_volume_id = volume['id']

        # CloudByte volume id equals OpenStack volume's provider_id
        cb_volume_id = volume.get('provider_id')

        LOG.debug("Will delete CloudByte volume [%(cb_vol)s] "
                  "w.r.t OpenStack volume [%(stack_vol)s].",
                  {'cb_vol': cb_volume_id, 'stack_vol': source_volume_id})

        # Delete volume at CloudByte
        if cb_volume_id is not None:

            cb_volumes = self._api_request_for_cloudbyte(
                'listFileSystem', params)

            # Search cb_volume_id in CloudByte volumes
            # incase it has already been deleted from CloudByte
            cb_volume_id = self._search_volume_id(cb_volumes, cb_volume_id)

            # Delete volume at CloudByte
            if cb_volume_id is not None:

                params = {"id": cb_volume_id}
                self._api_request_for_cloudbyte('deleteFileSystem', params)

                LOG.info(
                    _LI("Successfully deleted volume [%(cb_vol)s] "
                        "at CloudByte corresponding to "
                        "OpenStack volume [%(stack_vol)s]."),
                    {'cb_vol': cb_volume_id,
                     'stack_vol': source_volume_id})

            else:
                LOG.error(_LE("CloudByte does not have a volume corresponding "
                          "to OpenStack volume [%s]."), source_volume_id)

        else:
            LOG.error(_LE("CloudByte volume information not available for"
                      " OpenStack volume [%s]."), source_volume_id)

    def create_snapshot(self, snapshot):
        """Creates a snapshot at CloudByte."""

        # OpenStack volume
        source_volume_id = snapshot['volume_id']

        # CloudByte volume id equals OpenStack volume's provider_id
        cb_volume_id = snapshot.get('volume').get('provider_id')

        if cb_volume_id is not None:

            snapshot_name = snapshot['display_name']
            if snapshot_name is None or snapshot_name == '':
                # Generate the snapshot name
                snapshot_name = self._generate_snapshot_name()
                # Update the snapshot dict for later use
                snapshot['display_name'] = snapshot_name

            params = {
                "name": snapshot_name,
                "id": cb_volume_id
            }

            LOG.debug(
                "Will create CloudByte snapshot [%(cb_snap)s] "
                "w.r.t CloudByte volume [%(cb_vol)s] "
                "and OpenStack volume [%(stack_vol)s].",
                {'cb_snap': snapshot_name,
                 'cb_vol': cb_volume_id,
                 'stack_vol': source_volume_id})

            self._api_request_for_cloudbyte('createStorageSnapshot', params)

            # Get the snapshot path from CloudByte
            path = self._get_cb_snapshot_path(snapshot, cb_volume_id)

            LOG.info(
                _LI("Created CloudByte snapshot [%(cb_snap)s] "
                    "w.r.t CloudByte volume [%(cb_vol)s] "
                    "and OpenStack volume [%(stack_vol)s]."),
                {'cb_snap': path,
                 'cb_vol': cb_volume_id,
                 'stack_vol': source_volume_id})

            model_update = {}
            # Store snapshot path as snapshot provider_id
            model_update['provider_id'] = path

        else:
            msg = _("Failed to create snapshot. CloudByte volume information "
                    "not found for OpenStack volume [%s].") % source_volume_id
            raise exception.VolumeBackendAPIException(data=msg)

        return model_update

    def create_cloned_volume(self, cloned_volume, src_volume):
        """Create a clone of an existing volume.

        First it will create a snapshot of the source/parent volume,
        then it creates a clone of this newly created snapshot.
        """

        # Extract necessary information from input params
        parent_volume_id = cloned_volume.get('source_volid')

        # Generating name and id for snapshot
        # as this is not user entered in this particular usecase
        snapshot_name = self._generate_snapshot_name()

        snapshot_id = (six.text_type(parent_volume_id) + "_" +
                       time.strftime("%d%m%Y") + time.strftime("%H%M%S"))

        # Prepare the params for create_snapshot
        # as well as create_volume_from_snapshot method
        snapshot_params = {
            'id': snapshot_id,
            'display_name': snapshot_name,
            'volume_id': parent_volume_id,
            'volume': src_volume,
        }

        # Create a snapshot
        snapshot = self.create_snapshot(snapshot_params)
        snapshot_params['provider_id'] = snapshot.get('provider_id')

        # Create a clone of above snapshot
        return self.create_volume_from_snapshot(cloned_volume, snapshot_params)

    def create_volume_from_snapshot(self, cloned_volume, snapshot):
        """Create a clone from an existing snapshot."""

        # Getting necessary data from input params
        parent_volume_id = snapshot['volume_id']
        cloned_volume_name = cloned_volume['id'].replace("-", "")

        # CloudByte volume id equals OpenStack volume's provider_id
        cb_volume_id = snapshot.get('volume').get('provider_id')

        # CloudByte snapshot path equals OpenStack snapshot's provider_id
        cb_snapshot_path = snapshot['provider_id']

        params = {
            "id": cb_volume_id,
            "clonename": cloned_volume_name,
            "path": cb_snapshot_path
        }

        LOG.debug(
            "Will create CloudByte clone [%(cb_clone)s] "
            "at CloudByte snapshot path [%(cb_snap)s] "
            "w.r.t parent OpenStack volume [%(stack_vol)s].",
            {'cb_clone': cloned_volume_name,
             'cb_snap': cb_snapshot_path,
             'stack_vol': parent_volume_id})

        # Create clone of the snapshot
        clone_dataset_snapshot_res = (
            self._api_request_for_cloudbyte('cloneDatasetSnapshot', params))

        cb_snap = clone_dataset_snapshot_res.get('cloneDatasetSnapshot')

        cb_vol = {}
        if cb_snap is not None:
            cb_vol = cb_snap.get('filesystem')
        else:
            msg = ("Error: Clone creation failed for "
                   "OpenStack volume [%(vol)s] with CloudByte "
                   "snapshot path [%(path)s]" %
                   {'vol': parent_volume_id, 'path': cb_snapshot_path})
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.info(
            _LI("Created a clone [%(cb_clone)s] "
                "at CloudByte snapshot path [%(cb_snap)s] "
                "w.r.t parent OpenStack volume [%(stack_vol)s]."),
            {'cb_clone': cloned_volume_name,
             'cb_snap': cb_snapshot_path,
             'stack_vol': parent_volume_id})

        return self._build_provider_details_from_volume(cb_vol)

    def delete_snapshot(self, snapshot):
        """Delete a snapshot at CloudByte."""

        # Find volume id
        source_volume_id = snapshot['volume_id']

        # CloudByte volume id equals OpenStack volume's provider_id
        cb_volume_id = snapshot.get('volume').get('provider_id')

        # CloudByte snapshot path equals OpenStack snapshot's provider_id
        cb_snapshot_path = snapshot['provider_id']

        # If cb_snapshot_path is 'None'
        # then no need to execute CloudByte API
        if cb_snapshot_path is not None:

            params = {
                "id": cb_volume_id,
                "path": cb_snapshot_path
            }

            LOG.debug("Will delete CloudByte snapshot [%(snap)s] w.r.t "
                      "parent CloudByte volume [%(cb_vol)s] "
                      "and parent OpenStack volume [%(stack_vol)s].",
                      {'snap': cb_snapshot_path,
                       'cb_vol': cb_volume_id,
                       'stack_vol': source_volume_id})

            # Execute CloudByte API
            self._api_request_for_cloudbyte('deleteSnapshot', params)
            LOG.info(
                _LI("Deleted CloudByte snapshot [%(snap)s] w.r.t "
                    "parent CloudByte volume [%(cb_vol)s] "
                    "and parent OpenStack volume [%(stack_vol)s]."),
                {'snap': cb_snapshot_path,
                 'cb_vol': cb_volume_id,
                 'stack_vol': source_volume_id})

        else:
            LOG.error(_LE("CloudByte snapshot information is not available"
                      " for OpenStack volume [%s]."), source_volume_id)

    def extend_volume(self, volume, new_size):

        # CloudByte volume id equals OpenStack volume's provider_id
        cb_volume_id = volume.get('provider_id')

        params = {
            "id": cb_volume_id,
            "quotasize": six.text_type(new_size) + 'G'
        }

        # Request the CloudByte api to update the volume
        self._api_request_for_cloudbyte('updateFileSystem', params)

    def create_export(self, context, volume):
        """Setup the iscsi export info."""
        model_update = {}

        # Will provide CHAP Authentication on forthcoming patches/release
        model_update['provider_auth'] = None

        return model_update

    def ensure_export(self, context, volume):
        """Verify the iscsi export info."""
        model_update = {}

        # Will provide CHAP Authentication on forthcoming patches/release
        model_update['provider_auth'] = None

        return model_update

    def get_volume_stats(self, refresh=False):
        """Get volume statistics.

        If 'refresh' is True, update/refresh the statistics first.
        """

        if refresh:
            # Get the TSM name from configuration
            tsm_name = self.configuration.cb_tsm_name
            # Get the storage details of this TSM
            data = self._get_storage_info(tsm_name)

            data["volume_backend_name"] = (
                self.configuration.safe_get('volume_backend_name') or
                'CloudByte')
            data["vendor_name"] = 'CloudByte'
            data['reserved_percentage'] = 0
            data["driver_version"] = CloudByteISCSIDriver.VERSION
            data["storage_protocol"] = 'iSCSI'

            LOG.debug("CloudByte driver stats: [%s].", data)
            # Set this to the instance variable
            self.volume_stats = data

        return self.volume_stats
