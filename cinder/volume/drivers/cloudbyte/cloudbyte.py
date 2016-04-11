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

import json
import uuid

from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import units
import six
from six.moves import http_client
from six.moves import urllib

from cinder import context
from cinder import exception
from cinder.i18n import _, _LE, _LI
from cinder.volume.drivers.cloudbyte import options
from cinder.volume.drivers.san import san
from cinder.volume import qos_specs
from cinder.volume import volume_types

LOG = logging.getLogger(__name__)


class CloudByteISCSIDriver(san.SanISCSIDriver):
    """CloudByte ISCSI Driver.

    Version history:
        1.0.0 - Initial driver
        1.1.0 - Add chap support and minor bug fixes
        1.1.1 - Add wait logic for delete volumes
        1.1.2 - Update ig to None before delete volume
        1.2.0 - Add retype support
    """

    VERSION = '1.2.0'
    volume_stats = {}

    def __init__(self, *args, **kwargs):
        super(CloudByteISCSIDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(
            options.cloudbyte_add_qosgroup_opts)
        self.configuration.append_config_values(
            options.cloudbyte_create_volume_opts)
        self.configuration.append_config_values(
            options.cloudbyte_update_volume_opts)
        self.configuration.append_config_values(
            options.cloudbyte_connection_opts)
        self.cb_use_chap = self.configuration.use_chap_auth
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

        sanitized_params = urllib.parse.urlencode(sanitized_params)
        url = ('/client/api?%s' % sanitized_params)

        LOG.debug("CloudByte URL to be executed: [%s].", url)

        # Add the apikey
        api = {}
        api['apiKey'] = apikey
        url = url + '&' + urllib.parse.urlencode(api)

        return url

    def _extract_http_error(self, error_data):
        # Extract the error message from error_data
        error_msg = ""

        # error_data is a single key value dict
        for key, value in error_data.items():
            error_msg = value.get('errortext')

        return error_msg

    def _execute_and_get_response_details(self, host, url):
        """Will prepare response after executing an http request."""

        res_details = {}
        try:
            # Prepare the connection
            connection = http_client.HTTPSConnection(host)
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

        except http_client.HTTPException as ex:
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

    def _add_qos_group_request(self, volume, tsmid, volume_name,
                               qos_group_params):
        # Prepare the user input params
        params = {
            "name": "QoS_" + volume_name,
            "tsmid": tsmid
        }
        # Get qos related params from configuration
        params.update(self.configuration.cb_add_qosgroup)

        # Override the default configuration by qos specs
        if qos_group_params:
            params.update(qos_group_params)

        data = self._api_request_for_cloudbyte("addQosGroup", params)
        return data

    def _create_volume_request(self, volume, datasetid, qosgroupid,
                               tsmid, volume_name, file_system_params):

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
        params.update(self.configuration.cb_create_volume)

        # Override the default configuration by qos specs
        if file_system_params:
            params.update(file_system_params)

        data = self._api_request_for_cloudbyte("createVolume", params)
        return data

    def _queryAsyncJobResult_request(self, jobid):
        async_cmd = "queryAsyncJobResult"
        params = {
            "jobId": jobid,
        }
        data = self._api_request_for_cloudbyte(async_cmd, params)
        return data

    def _get_tsm_details(self, data, tsm_name, account_name):
        # Filter required tsm's details
        tsms = data['listTsmResponse'].get('listTsm')

        if tsms is None:
            msg = (_("TSM [%(tsm)s] was not found in CloudByte storage "
                   "for account [%(account)s].") %
                   {'tsm': tsm_name, 'account': account_name})
            raise exception.VolumeBackendAPIException(data=msg)

        tsmdetails = {}
        for tsm in tsms:
            if tsm['name'] == tsm_name:
                tsmdetails['datasetid'] = tsm['datasetid']
                tsmdetails['tsmid'] = tsm['id']
                break

        return tsmdetails

    def _retry_volume_operation(self, operation, retries,
                                max_retries, jobid,
                                cb_volume):
        """CloudByte async calls via the FixedIntervalLoopingCall."""

        # Query the CloudByte storage with this jobid
        volume_response = self._queryAsyncJobResult_request(jobid)
        count = retries['count']

        result_res = None
        if volume_response is not None:
            result_res = volume_response.get('queryasyncjobresultresponse')

        if result_res is None:
            msg = (_(
                "Null response received while querying "
                "for [%(operation)s] based job [%(job)s] "
                "at CloudByte storage.") %
                {'operation': operation, 'job': jobid})
            raise exception.VolumeBackendAPIException(data=msg)

        status = result_res.get('jobstatus')

        if status == 1:
            LOG.info(_LI("CloudByte operation [%(operation)s] succeeded for "
                         "volume [%(cb_volume)s]."),
                     {'operation': operation, 'cb_volume': cb_volume})
            raise loopingcall.LoopingCallDone()
        elif status == 2:
            job_result = result_res.get("jobresult")
            err_msg = job_result.get("errortext")
            err_code = job_result.get("errorcode")
            msg = (_(
                "Error in Operation [%(operation)s] "
                "for volume [%(cb_volume)s] in CloudByte "
                "storage: [%(cb_error)s], "
                "error code: [%(error_code)s]."),
                {'cb_error': err_msg,
                 'error_code': err_code,
                 'cb_volume': cb_volume,
                 'operation': operation})
            raise exception.VolumeBackendAPIException(data=msg)
        elif count == max_retries:
            # All attempts exhausted
            LOG.error(_LE("CloudByte operation [%(operation)s] failed"
                          " for volume [%(vol)s]. Exhausted all"
                          " [%(max)s] attempts."),
                      {'operation': operation,
                       'vol': cb_volume,
                       'max': max_retries})
            raise loopingcall.LoopingCallDone(retvalue=False)
        else:
            count += 1
            retries['count'] = count
            LOG.debug("CloudByte operation [%(operation)s] for"
                      " volume [%(vol)s]: retry [%(retry)s] of [%(max)s].",
                      {'operation': operation,
                       'vol': cb_volume,
                       'retry': count,
                       'max': max_retries})

    def _wait_for_volume_creation(self, volume_response, cb_volume_name):
        """Given the job wait for it to complete."""

        vol_res = volume_response.get('createvolumeresponse')

        if vol_res is None:
            msg = _("Null response received while creating volume [%s] "
                    "at CloudByte storage.") % cb_volume_name
            raise exception.VolumeBackendAPIException(data=msg)

        jobid = vol_res.get('jobid')

        if jobid is None:
            msg = _("Job id not found in CloudByte's "
                    "create volume [%s] response.") % cb_volume_name
            raise exception.VolumeBackendAPIException(data=msg)

        retry_interval = (
            self.configuration.cb_confirm_volume_create_retry_interval)

        max_retries = (
            self.configuration.cb_confirm_volume_create_retries)
        retries = {'count': 0}

        timer = loopingcall.FixedIntervalLoopingCall(
            self._retry_volume_operation,
            'Create Volume',
            retries,
            max_retries,
            jobid,
            cb_volume_name)
        timer.start(interval=retry_interval).wait()

    def _wait_for_volume_deletion(self, volume_response, cb_volume_id):
        """Given the job wait for it to complete."""

        vol_res = volume_response.get('deleteFileSystemResponse')

        if vol_res is None:
            msg = _("Null response received while deleting volume [%s] "
                    "at CloudByte storage.") % cb_volume_id
            raise exception.VolumeBackendAPIException(data=msg)

        jobid = vol_res.get('jobid')

        if jobid is None:
            msg = _("Job id not found in CloudByte's "
                    "delete volume [%s] response.") % cb_volume_id
            raise exception.VolumeBackendAPIException(data=msg)

        retry_interval = (
            self.configuration.cb_confirm_volume_delete_retry_interval)

        max_retries = (
            self.configuration.cb_confirm_volume_delete_retries)
        retries = {'count': 0}

        timer = loopingcall.FixedIntervalLoopingCall(
            self._retry_volume_operation,
            'Delete Volume',
            retries,
            max_retries,
            jobid,
            cb_volume_id)
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

    def _build_provider_details_from_volume(self, volume, chap):
        model_update = {}

        model_update['provider_location'] = (
            '%s %s %s' % (volume['ipaddress'] + ':3260', volume['iqnname'], 0)
        )

        # Will provide CHAP Authentication on forthcoming patches/release
        model_update['provider_auth'] = None

        if chap:
            model_update['provider_auth'] = ('CHAP %(username)s %(password)s'
                                             % chap)

        model_update['provider_id'] = volume['id']

        LOG.debug("CloudByte volume iqn: [%(iqn)s] provider id: [%(proid)s].",
                  {'iqn': volume['iqnname'], 'proid': volume['id']})

        return model_update

    def _build_provider_details_from_response(self,
                                              cb_volumes,
                                              volume_name,
                                              chap):
        """Get provider information."""

        model_update = {}
        volumes = cb_volumes['listFilesystemResponse']['filesystem']

        for vol in volumes:
            if vol['name'] == volume_name:
                model_update = self._build_provider_details_from_volume(vol,
                                                                        chap)
                break

        return model_update

    def _get_initiator_group_id_from_response(self, data, filter):
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
            if ig.get('initiatorgroup') == filter:
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

    def _request_update_iscsi_service(self, iscsi_id, ig_id, ag_id):
        params = {
            "id": iscsi_id,
            "igid": ig_id
        }

        if ag_id:
            params['authgroupid'] = ag_id
            params['authmethod'] = "CHAP"

        self._api_request_for_cloudbyte(
            'updateVolumeiSCSIService', params)

    def _get_cb_snapshot_path(self, snapshot_name, volume_id):
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
            if snap['name'] == snapshot_name:
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

    def _get_auth_group_id_from_response(self, data):
        """Find iSCSI auth group id."""

        chap_group = self.configuration.cb_auth_group

        ag_list_res = data.get('listiSCSIAuthGroupResponse')

        if ag_list_res is None:
            msg = _("Null response received from CloudByte's "
                    "list iscsi auth groups.")
            raise exception.VolumeBackendAPIException(data=msg)

        ag_list = ag_list_res.get('authgroup')

        if ag_list is None:
            msg = _('No iscsi auth groups were found in CloudByte.')
            raise exception.VolumeBackendAPIException(data=msg)

        ag_id = None

        for ag in ag_list:
            if ag.get('name') == chap_group:
                ag_id = ag['id']
                break
        else:
            msg = _("Auth group [%s] details not found in "
                    "CloudByte storage.") % chap_group
            raise exception.VolumeBackendAPIException(data=msg)

        return ag_id

    def _get_auth_group_info(self, account_id, ag_id):
        """Fetch the auth group details."""

        params = {"accountid": account_id, "authgroupid": ag_id}

        auth_users = self._api_request_for_cloudbyte(
            'listiSCSIAuthUser', params)

        auth_user_details_res = auth_users.get('listiSCSIAuthUsersResponse')

        if auth_user_details_res is None:
            msg = _("No response was received from CloudByte storage "
                    "list iSCSI auth user API call.")
            raise exception.VolumeBackendAPIException(data=msg)

        auth_user_details = auth_user_details_res.get('authuser')

        if auth_user_details is None:
            msg = _("Auth user details not found in CloudByte storage.")
            raise exception.VolumeBackendAPIException(data=msg)

        chapuser = auth_user_details[0].get('chapusername')
        chappassword = auth_user_details[0].get('chappassword')

        if chapuser is None or chappassword is None:
            msg = _("Invalid chap user details found in CloudByte storage.")
            raise exception.VolumeBackendAPIException(data=msg)

        data = {'username': chapuser, 'password': chappassword, 'ag_id': ag_id}

        return data

    def _get_chap_info(self, account_id):
        """Fetch the chap details."""

        params = {"accountid": account_id}

        iscsi_auth_data = self._api_request_for_cloudbyte(
            'listiSCSIAuthGroup', params)

        ag_id = self._get_auth_group_id_from_response(
            iscsi_auth_data)

        return self._get_auth_group_info(account_id, ag_id)

    def _export(self):
        model_update = {'provider_auth': None}

        if self.cb_use_chap is True:
            account_name = self.configuration.cb_account_name

            account_id = self._get_account_id_from_name(account_name)

            chap = self._get_chap_info(account_id)

            model_update['provider_auth'] = ('CHAP %(username)s %(password)s'
                                             % chap)

        return model_update

    def _update_initiator_group(self, volume_id, ig_name):

        # Get account id of this account
        account_name = self.configuration.cb_account_name
        account_id = self._get_account_id_from_name(account_name)

        # Fetch the initiator group ID
        params = {"accountid": account_id}

        iscsi_initiator_data = self._api_request_for_cloudbyte(
            'listiSCSIInitiator', params)

        # Filter the list of initiator groups with the name
        ig_id = self._get_initiator_group_id_from_response(
            iscsi_initiator_data, ig_name)

        params = {"storageid": volume_id}

        iscsi_service_data = self._api_request_for_cloudbyte(
            'listVolumeiSCSIService', params)
        iscsi_id = self._get_iscsi_service_id_from_response(
            volume_id, iscsi_service_data)

        # Update the iscsi service with above fetched iscsi_id
        self._request_update_iscsi_service(iscsi_id, ig_id, None)

        LOG.debug("CloudByte initiator group updated successfully for volume "
                  "[%(vol)s] with ig [%(ig)s].",
                  {'vol': volume_id,
                   'ig': ig_name})

    def _get_qos_by_volume_type(self, ctxt, type_id):
        """Get the properties which can be QoS or file system related."""

        update_qos_group_params = {}
        update_file_system_params = {}

        volume_type = volume_types.get_volume_type(ctxt, type_id)
        qos_specs_id = volume_type.get('qos_specs_id')
        extra_specs = volume_type.get('extra_specs')

        if qos_specs_id is not None:
            specs = qos_specs.get_qos_specs(ctxt, qos_specs_id)['specs']

            # Override extra specs with specs
            # Hence specs will prefer QoS than extra specs
            extra_specs.update(specs)

        for key, value in extra_specs.items():
            if ':' in key:
                fields = key.split(':')
                key = fields[1]

            if key in self.configuration.cb_update_qos_group:
                update_qos_group_params[key] = value

            elif key in self.configuration.cb_update_file_system:
                update_file_system_params[key] = value

        return update_qos_group_params, update_file_system_params

    def create_volume(self, volume):

        qos_group_params = {}
        file_system_params = {}
        tsm_name = self.configuration.cb_tsm_name
        account_name = self.configuration.cb_account_name

        # Get account id of this account
        account_id = self._get_account_id_from_name(account_name)

        # Set backend storage volume name using OpenStack volume id
        cb_volume_name = volume['id'].replace("-", "")

        ctxt = context.get_admin_context()
        type_id = volume['volume_type_id']

        if type_id is not None:
            qos_group_params, file_system_params = (
                self._get_qos_by_volume_type(ctxt, type_id))

        LOG.debug("Will create a volume [%(cb_vol)s] in TSM [%(tsm)s] "
                  "at CloudByte storage w.r.t "
                  "OpenStack volume [%(stack_vol)s].",
                  {'cb_vol': cb_volume_name,
                   'stack_vol': volume.get('id'),
                   'tsm': tsm_name})

        tsm_data = self._request_tsm_details(account_id)
        tsm_details = self._get_tsm_details(tsm_data, tsm_name, account_name)

        # Send request to create a qos group before creating a volume
        LOG.debug("Creating qos group for CloudByte volume [%s].",
                  cb_volume_name)
        qos_data = self._add_qos_group_request(
            volume, tsm_details.get('tsmid'), cb_volume_name, qos_group_params)

        # Extract the qos group id from response
        qosgroupid = qos_data['addqosgroupresponse']['qosgroup']['id']

        LOG.debug("Successfully created qos group for CloudByte volume [%s].",
                  cb_volume_name)

        # Send a create volume request to CloudByte API
        vol_data = self._create_volume_request(
            volume, tsm_details.get('datasetid'), qosgroupid,
            tsm_details.get('tsmid'), cb_volume_name, file_system_params)

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
            iscsi_initiator_data, 'ALL')

        LOG.debug("Updating iscsi service for CloudByte volume [%s].",
                  cb_volume_name)

        ag_id = None
        chap_info = {}

        if self.cb_use_chap is True:
            chap_info = self._get_chap_info(account_id)
            ag_id = chap_info['ag_id']

        # Update the iscsi service with above fetched iscsi_id & ig_id
        self._request_update_iscsi_service(iscsi_id, ig_id, ag_id)

        LOG.debug("CloudByte volume [%(vol)s] updated with "
                  "iscsi id [%(iscsi)s] and initiator group [%(ig)s] and "
                  "authentication group [%(ag)s].",
                  {'vol': cb_volume_name, 'iscsi': iscsi_id,
                   'ig': ig_id, 'ag': ag_id})

        # Provide the model after successful completion of above steps
        provider = self._build_provider_details_from_response(
            cb_volumes, cb_volume_name, chap_info)

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
                # Need to set the initiator group to None before deleting
                self._update_initiator_group(cb_volume_id, 'None')

                params = {"id": cb_volume_id}
                del_res = self._api_request_for_cloudbyte('deleteFileSystem',
                                                          params)

                self._wait_for_volume_deletion(del_res, cb_volume_id)

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

            # Set backend storage snapshot name using OpenStack snapshot id
            snapshot_name = "snap_" + snapshot['id'].replace("-", "")

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
            path = self._get_cb_snapshot_path(snapshot_name, cb_volume_id)

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
        parent_volume_id = src_volume.get('id')

        # Generating id for snapshot
        # as this is not user entered in this particular usecase
        snapshot_id = six.text_type(uuid.uuid1())

        # Prepare the params for create_snapshot
        # as well as create_volume_from_snapshot method
        snapshot_params = {
            'id': snapshot_id,
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

        chap_info = {}

        if self.cb_use_chap is True:
            account_name = self.configuration.cb_account_name

            # Get account id of this account
            account_id = self._get_account_id_from_name(account_name)

            chap_info = self._get_chap_info(account_id)

        model_update = self._build_provider_details_from_volume(cb_vol,
                                                                chap_info)

        return model_update

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

    def create_export(self, context, volume, connector):
        """Setup the iscsi export info."""

        return self._export()

    def ensure_export(self, context, volume):
        """Verify the iscsi export info."""

        return self._export()

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

    def retype(self, ctxt, volume, new_type, diff, host):
        """Retypes a volume, QoS and file system update is only done."""

        cb_volume_id = volume.get('provider_id')

        if cb_volume_id is None:
            message = _("Provider information w.r.t CloudByte storage "
                        "was not found for OpenStack "
                        "volume [%s].") % volume['id']

            raise exception.VolumeBackendAPIException(message)

        update_qos_group_params, update_file_system_params = (
            self._get_qos_by_volume_type(ctxt, new_type['id']))

        if update_qos_group_params:
            list_file_sys_params = {'id': cb_volume_id}
            response = self._api_request_for_cloudbyte(
                'listFileSystem', list_file_sys_params)

            response = response['listFilesystemResponse']
            cb_volume_list = response['filesystem']
            cb_volume = cb_volume_list[0]

            if not cb_volume:
                msg = (_("Volume [%(cb_vol)s] was not found at "
                         "CloudByte storage corresponding to OpenStack "
                         "volume [%(ops_vol)s].") %
                       {'cb_vol': cb_volume_id, 'ops_vol': volume['id']})

                raise exception.VolumeBackendAPIException(data=msg)

            update_qos_group_params['id'] = cb_volume.get('groupid')

            self._api_request_for_cloudbyte(
                'updateQosGroup', update_qos_group_params)

        if update_file_system_params:
            update_file_system_params['id'] = cb_volume_id
            self._api_request_for_cloudbyte(
                'updateFileSystem', update_file_system_params)

        LOG.info(_LI("Successfully updated CloudByte volume [%(cb_vol)s] "
                     "corresponding to OpenStack volume [%(ops_vol)s]."),
                 {'cb_vol': cb_volume_id, 'ops_vol': volume['id']})

        return True
