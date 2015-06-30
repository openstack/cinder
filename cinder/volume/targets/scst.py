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

from oslo_concurrency import processutils as putils
from oslo_log import log as logging

from cinder import exception
from cinder import utils
from cinder.i18n import _, _LE
from cinder.volume.targets import iscsi
from cinder.volume import utils as vutils

LOG = logging.getLogger(__name__)


class SCSTAdm(iscsi.ISCSITarget):

    def __init__(self, *args, **kwargs):
        super(SCSTAdm, self).__init__(*args, **kwargs)
        self.volumes_dir = self.configuration.safe_get('volumes_dir')
        self.iscsi_target_prefix = self.configuration.safe_get(
            'iscsi_target_prefix')
        self.target_name = self.configuration.safe_get('scst_target_iqn_name')
        self.target_driver = self.configuration.safe_get('scst_target_driver')
        self.chap_username = self.configuration.safe_get('chap_username')
        self.chap_password = self.configuration.safe_get('chap_password')
        self.initiator_iqn = None
        self.remove_initiator_iqn = None

    def scst_execute(self, *args):
        return utils.execute('scstadmin', *args, run_as_root=True)

    def validate_connector(self, connector):
        # iSCSI drivers require the initiator information
        if 'initiator' not in connector:
            err_msg = _('The volume driver requires the iSCSI initiator '
                        'name in the connector.')
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)
        self.initiator_iqn = connector['initiator']

    def terminate_connection(self, volume, connector, **kwargs):
        self.remove_initiator_iqn = connector['initiator']

    def _get_target(self, iqn):
        (out, _err) = self.scst_execute('-list_target')
        if iqn in out:
            return self._target_attribute(iqn)
        return None

    def _target_attribute(self, iqn):
        (out, _err) = self.scst_execute('-list_tgt_attr', iqn,
                                        '-driver', self.target_driver)
        lines = out.split('\n')
        for line in lines:
            if "rel_tgt_id" in line:
                parsed = line.split()
                return parsed[1]

    def _get_group(self):
        scst_group = "%s%s" % (self.initiator_iqn, self.target_name)
        (out, _err) = self.scst_execute('-list_group')
        if scst_group in out:
            return out
        return None

    def _get_luns_info(self):
        scst_group = "%s%s" % (self.initiator_iqn, self.target_name)
        (out, _err) = self.scst_execute('-list_group', scst_group,
                                        '-driver', self.target_driver,
                                        '-target', self.target_name)

        first = "Assigned LUNs:"
        last = "Assigned Initiators:"
        start = out.index(first) + len(first)
        end = out.index(last, start)
        out = out[start:end]

        luns = []
        for line in out.strip().split("\n")[2:]:
            luns.append(int(line.strip().split(" ")[0]))
        luns = sorted(set(luns))
        return luns

    def _get_target_and_lun(self, context, volume):
        iscsi_target = 0
        if not self.target_name or not self._get_group():
            lun = 1
            return iscsi_target, lun

        luns = self._get_luns_info()
        if (not luns) or (luns[0] != 1):
            lun = 1
            return iscsi_target, lun
        else:
            for lun in luns:
                if (luns[-1] == lun) or (luns[lun - 1] + 1 != luns[lun]):
                    return iscsi_target, (lun + 1)

    def create_iscsi_target(self, name, vol_id, tid, lun, path,
                            chap_auth=None):
        scst_group = "%s%s" % (self.initiator_iqn, self.target_name)
        vol_name = path.split("/")[3]
        try:
            (out, _err) = self.scst_execute('-noprompt',
                                            '-set_drv_attr',
                                            self.target_driver,
                                            '-attributes',
                                            'enabled=1')
            LOG.debug('StdOut from set driver attribute: %s', out)
        except putils.ProcessExecutionError as e:
            LOG.error(_LE("Failed to set attribute for enable target driver "
                          "%s"), e)
            raise exception.ISCSITargetHelperCommandFailed(
                error_message="Failed to enable SCST Target driver.")

        if self._get_target(name) is None:
            try:
                (out, _err) = self.scst_execute('-add_target', name,
                                                '-driver', self.target_driver)
                LOG.debug("StdOut from scstadmin create target: %s", out)
            except putils.ProcessExecutionError as e:
                LOG.error(_LE("Failed to create iscsi target for volume "
                          "id:%(vol_id)s: %(e)s"), {'vol_id': name, 'e': e})
                raise exception.ISCSITargetCreateFailed(volume_id=vol_name)
            try:
                (out, _err) = self.scst_execute('-enable_target', name,
                                                '-driver', self.target_driver)
                LOG.debug("StdOut from scstadmin enable target: %s", out)
            except putils.ProcessExecutionError as e:
                LOG.error(_LE("Failed to set 'enable' attribute for "
                              "SCST target %s"), e)
                raise exception.ISCSITargetHelperCommandFailed(
                    error_mesage="Failed to enable SCST Target.")
            if chap_auth and self.target_name:
                try:
                    chap_string = self._iscsi_authentication('IncomingUser=',
                                                             *chap_auth)
                    (out, _err) = self.scst_execute('-noprompt',
                                                    '-set_tgt_attr', name,
                                                    '-driver',
                                                    self.target_driver,
                                                    '-attributes',
                                                    chap_string)
                    LOG.debug("StdOut from scstadmin set target attribute:"
                              " %s.", out)
                except putils.ProcessExecutionError:
                    msg = _("Failed to set attribute 'Incoming user' for "
                            "SCST target.")
                    LOG.exception(msg)
                    raise exception.ISCSITargetHelperCommandFailed(
                        error_mesage=msg)

        if self.target_name:
            if self._get_group() is None:
                try:
                    (out, _err) = self.scst_execute('-add_group', scst_group,
                                                    '-driver',
                                                    self.target_driver,
                                                    '-target', name)
                    LOG.debug("StdOut from scstadmin create group: %s", out)
                except putils.ProcessExecutionError as e:
                    LOG.error(_LE("Failed to create group to SCST target "
                                  "%s"), e)
                    raise exception.ISCSITargetHelperCommandFailed(
                        error_message="Failed to create group to SCST target.")
            try:
                (out, _err) = self.scst_execute('-add_init',
                                                self.initiator_iqn,
                                                '-driver', self.target_driver,
                                                '-target', name,
                                                '-group', scst_group)
                LOG.debug("StdOut from scstadmin add initiator: %s", out)
            except putils.ProcessExecutionError as e:
                LOG.error(_LE("Failed to add initiator to group "
                          " for SCST target %s"), e)
                raise exception.ISCSITargetHelperCommandFailed(
                    error_message="Failed to add Initiator to group for "
                                  "SCST target.")

        tid = self._get_target(name)
        if self.target_name is None:
            disk_id = "disk%s" % tid
        else:
            disk_id = "%s%s" % (lun, vol_id.split('-')[-1])

        try:
            self.scst_execute('-open_dev', disk_id,
                              '-handler', 'vdisk_fileio',
                              '-attributes', 'filename=%s' % path)
        except putils.ProcessExecutionError as e:
            LOG.error(_LE("Failed to add device to handler %s"), e)
            raise exception.ISCSITargetHelperCommandFailed(
                error_message="Failed to add device to SCST handler.")

        try:
            if self.target_name:
                self.scst_execute('-add_lun', lun,
                                  '-driver', self.target_driver,
                                  '-target', name,
                                  '-device', disk_id,
                                  '-group', scst_group)
            else:
                self.scst_execute('-add_lun', lun,
                                  '-driver', self.target_driver,
                                  '-target', name,
                                  '-device', disk_id)
        except putils.ProcessExecutionError as e:
            LOG.error(_LE("Failed to add lun to SCST target "
                      "id:%(vol_id)s: %(e)s"), {'vol_id': name, 'e': e})
            raise exception.ISCSITargetHelperCommandFailed(
                error_message="Failed to add LUN to SCST Target for "
                              "volume " + vol_name)

            # SCST uses /etc/scst.conf as the default configuration when it
            # starts
        try:
            self.scst_execute('-write_config', '/etc/scst.conf')
        except putils.ProcessExecutionError as e:
            LOG.error(_LE("Failed to write in /etc/scst.conf."))
            raise exception.ISCSITargetHelperCommandFailed(
                error_message="Failed to write in /etc/scst.conf.")

        return tid

    def _iscsi_location(self, ip, target, iqn, lun=None):
        return "%s:%s,%s %s %s" % (ip, self.configuration.iscsi_port,
                                   target, iqn, lun)

    def _get_iscsi_target(self, context, vol_id):
        # FIXME(jdg): Need to implement abc method
        pass

    def _get_target_chap_auth(self, context, iscsi_name):
        # FIXME(jdg): Need to implement abc method

        if self._get_target(iscsi_name) is None:
            return None
        (out, _err) = self.scst_execute('-list_tgt_attr', iscsi_name,
                                        '-driver', self.target_driver)
        first = "KEY"
        last = "Dynamic attributes"
        start = out.index(first) + len(first)
        end = out.index(last, start)
        out = out[start:end]
        out = out.split("\n")[2]
        if "IncomingUser" in out:
            out = out.split(" ")
            out = filter(lambda a: a != "", out)
            return (out[1], out[2])
        else:
            return None

    def ensure_export(self, context, volume, volume_path):
        iscsi_target, lun = self._get_target_and_lun(context, volume)
        if self.target_name is None:
            iscsi_name = "%s%s" % (self.configuration.iscsi_target_prefix,
                                   volume['name'])
        else:
            iscsi_name = self.target_name

        if self.chap_username and self.chap_password:
            chap_auth = (self.chap_username, self.chap_password)
        else:
            chap_auth = self._get_target_chap_auth(context, iscsi_name)

        self.create_iscsi_target(iscsi_name, volume['id'], iscsi_target,
                                 lun, volume_path, chap_auth)

    def create_export(self, context, volume, volume_path):
        """Creates an export for a logical volume."""
        iscsi_target, lun = self._get_target_and_lun(context, volume)
        if self.target_name is None:
            iscsi_name = "%s%s" % (self.configuration.iscsi_target_prefix,
                                   volume['name'])
        else:
            iscsi_name = self.target_name

        if self.chap_username and self.chap_password:
            chap_auth = (self.chap_username, self.chap_password)
        else:
            chap_auth = self._get_target_chap_auth(context, iscsi_name)
            if not chap_auth:
                chap_auth = (vutils.generate_username(),
                             vutils.generate_password())
        tid = self.create_iscsi_target(iscsi_name, volume['id'], iscsi_target,
                                       lun, volume_path, chap_auth)

        data = {}
        data['location'] = self._iscsi_location(
            self.configuration.iscsi_ip_address, tid, iscsi_name, lun)
        LOG.debug('Set provider_location to: %s', data['location'])
        data['auth'] = self._iscsi_authentication(
            'CHAP', *chap_auth)
        return data

    def remove_export(self, context, volume):
        try:
            location = volume['provider_location'].split(' ')
            iqn = location[1]
            iscsi_target = self._get_target(iqn)
            self.show_target(iscsi_target, iqn)

        except Exception:
            LOG.error(_LE("Skipping remove_export. No iscsi_target is"
                          "presently exported for volume: %s"), volume['id'])
            return
        vol = self.db.volume_get(context, volume['id'])
        lun = "".join(vol['provider_location'].split(" ")[-1:])

        self.remove_iscsi_target(iscsi_target, lun,
                                 volume['id'], volume['name'])

    def remove_iscsi_target(self, tid, lun, vol_id, vol_name, **kwargs):
        disk_id = "%s%s" % (lun, vol_id.split('-')[-1])
        vol_uuid_file = vol_name
        if self.target_name is None:
            iqn = '%s%s' % (self.iscsi_target_prefix, vol_uuid_file)
        else:
            iqn = self.target_name

        if self.target_name is None:
            try:
                self.scst_execute('-noprompt',
                                  '-rem_target', iqn,
                                  '-driver', 'iscsi')
            except putils.ProcessExecutionError as e:
                LOG.error(_LE("Failed to remove iscsi target for volume "
                          "id:%(vol_id)s: %(e)s"), {'vol_id': vol_id, 'e': e})
                raise exception.ISCSITargetRemoveFailed(volume_id=vol_id)
            try:
                self.scst_execute('-noprompt',
                                  '-close_dev', "disk%s" % tid,
                                  '-handler', 'vdisk_fileio')
            except putils.ProcessExecutionError as e:
                LOG.error(_LE("Failed to close disk device %s"), e)
                raise exception.ISCSITargetHelperCommandFailed(
                    error_message="Failed to close disk device for "
                                  "SCST handler.")

            if self._get_target(iqn):
                try:
                    self.scst_execute('-noprompt',
                                      '-rem_target', iqn,
                                      '-driver', self.target_driver)
                except putils.ProcessExecutionError as e:
                    LOG.error(_LE("Failed to remove iscsi target for "
                                  "volume id:%(vol_id)s: %(e)s"),
                              {'vol_id': vol_id, 'e': e})
                    raise exception.ISCSITargetRemoveFailed(volume_id=vol_id)
        else:
            if not int(lun) in self._get_luns_info():
                raise exception.ISCSITargetRemoveFailed(volume_id=vol_id)
            try:
                scst_group = "%s%s" % (self.remove_initiator_iqn,
                                       self.target_name)
                self.scst_execute('-noprompt', '-rem_lun', lun,
                                  '-driver', self.target_driver,
                                  '-target', iqn, '-group',
                                  scst_group)
            except putils.ProcessExecutionError as e:
                LOG.error(_LE("Failed to remove LUN %s"), e)
                raise exception.ISCSITargetHelperCommandFailed(
                    error_message="Failed to remove LUN for SCST Target.")

            try:
                self.scst_execute('-noprompt',
                                  '-close_dev', disk_id,
                                  '-handler', 'vdisk_fileio')
            except putils.ProcessExecutionError as e:
                LOG.error(_LE("Failed to close disk device %s"), e)
                raise exception.ISCSITargetHelperCommandFailed(
                    error_message="Failed to close disk device for "
                                  "SCST handler.")

        self.scst_execute('-write_config', '/etc/scst.conf')

    def show_target(self, tid, iqn):
        if iqn is None:
            raise exception.InvalidParameterValue(
                err=_('valid iqn needed for show_target'))

        tid = self._get_target(iqn)
        if tid is None:
            raise exception.ISCSITargetHelperCommandFailed(
                error_message="Target not found")
