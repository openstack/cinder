# Copyright (c) 2019 FUJITSU LIMITED
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
#

"""Cinder Volume driver for Fujitsu ETERNUS DX S3 series."""

from cinder.i18n import _
from cinder import ssh_utils


class FJDXCLI(object):
    """ETERNUS CLI Code."""

    def __init__(self, user, storage_ip, password=None, keyfile=None):
        """Constructor."""
        self.user = user
        self.storage_ip = storage_ip
        if password and keyfile:
            raise Exception(_('can not specify both password and keyfile'))

        self.use_ipv6 = False
        if storage_ip.find(':') != -1:
            self.use_ipv6 = True

        if password:
            self.ssh_pool = ssh_utils.SSHPool(storage_ip, 22, None, user,
                                              password=password, max_size=2)

        if keyfile:
            self.ssh_pool = ssh_utils.SSHPool(storage_ip, 22, None, user,
                                              privatekey=keyfile, max_size=2)

        self.ce_support = False
        self.CMD_dic = {
            'check_user_role': self._check_user_role,
            'expand_volume': self._expand_volume,
            'show_pool_provision': self._show_pool_provision,
            'show_qos_bandwidth_limit': self._show_qos_bandwidth_limit,
            'set_qos_bandwidth_limit': self._set_qos_bandwidth_limit,
            'set_volume_qos': self._set_volume_qos,
            'show_copy_sessions': self._show_copy_sessions,
            'show_volume_qos': self._show_volume_qos,
            'show_enclosure_status': self._show_enclosure_status,
            'start_copy_snap_opc': self._start_copy_snap_opc,
            'stop_copy_session': self._stop_copy_session,
            'start_copy_opc': self._start_copy_opc,
            'delete_volume': self._delete_volume
        }

        self.SMIS_dic = {
            '0000': '0',  # Success.
            '0060': '32787',  # The device is in busy state.
            '0100': '4097'
        }  # Size not supported.

    def done(self, command, **option):
        func = self.CMD_dic.get(command, self._default_func)
        return func(**option)

    def _exec_cli(self, cmd, StrictHostKeyChecking=True, **option):

        exec_cmdline = cmd + self._get_option(**option)
        stdoutdata = self._exec_cli_with_eternus(exec_cmdline)
        output = []
        message = []
        stdoutlist = stdoutdata.split('\r\n')
        output_header = ""

        for no, outline in enumerate(stdoutlist):
            if len(outline) <= 0 or outline is None:
                continue

            if not output_header.endswith(exec_cmdline):
                output_header += outline
                continue

            if 0 <= outline.find('Error'):
                raise Exception(_("Output: %(outline)s: "
                                  "Command: %(cmdline)s")
                                % {'outline': outline,
                                   'cmdline': exec_cmdline})

            if not self._is_status(outline):
                continue

            status = int(outline, 16)
            lineno = no + 1
            break
        else:
            raise Exception(_(
                "Invalid CLI output: %(exec_cmdline)s, %(stdoutlist)s")
                % {'exec_cmdline': exec_cmdline,
                   'stdoutlist': stdoutlist})

        if status == 0:
            rc = '0'
            for outline in stdoutlist[lineno:]:
                if 0 <= outline.find('CLI>'):
                    continue
                if len(outline) <= 0:
                    continue
                if outline is None:
                    continue
                message.append(outline)
        else:
            code = stdoutlist[lineno]
            for outline in stdoutlist[lineno + 1:]:
                if 0 <= outline.find('CLI>'):
                    continue
                if len(outline) <= 0:
                    continue
                if outline is None:
                    continue
                output.append(outline)

            rc, message = self._create_error_message(code, output)

        return {'result': 0, 'rc': rc, 'message': message}

    def _exec_cli_with_eternus(self, exec_cmdline):
        """Execute CLI command with arguments."""
        ssh = None
        try:
            ssh = self.ssh_pool.get()
            chan = ssh.invoke_shell()
            chan.send(exec_cmdline + '\n')
            stdoutdata = ''
            while True:
                temp = chan.recv(65535)
                if isinstance(temp, bytes):
                    temp = temp.decode('utf-8')
                else:
                    temp = str(temp)
                stdoutdata += temp

                # CLI command end with 'CLI>'.
                if stdoutdata == '\r\nCLI> ':
                    continue
                if (stdoutdata[len(stdoutdata) - 5: len(stdoutdata) - 1] ==
                        'CLI>'):
                    break
        except Exception as e:
            raise Exception(_("Execute CLI "
                              "command error. Error: %s") % e)
        finally:
            if ssh:
                self.ssh_pool.put(ssh)
                self.ssh_pool.remove(ssh)
        return stdoutdata

    def _create_error_message(self, code, msg):
        """Create error code and message using arguements."""
        message = None
        if code in self.SMIS_dic:
            rc = self.SMIS_dic[code]
        else:
            rc = 'E' + code

            # TODO(whfnst): we will have a dic to store errors.
            if rc == "E0001":
                message = "Bad value: %s" % msg
            elif rc == "ED184":
                message = "Because OPC is being executed, "
                "the processing was discontinued."
            else:
                message = msg

        return rc, message

    @staticmethod
    def _is_status(value):
        """Check whether input value is status value or not."""
        try:
            if len(value) != 2:
                return False

            int(value, 16)
            int(value[0], 16)
            int(value[1], 16)

            return True
        except ValueError:
            return False

    @staticmethod
    def _get_option(**option):
        """Create option strings from dictionary."""
        ret = ""
        for key, value in option.items():
            ret += " -%(key)s %(value)s" % {'key': key, 'value': value}
        return ret

    def _default_func(self, **option):
        """Default function."""
        raise Exception(_("Invalid function is specified"))

    def _check_user_role(self, **option):
        """Check user role."""
        try:
            output = self._exec_cli("show users",
                                    StrictHostKeyChecking=False,
                                    **option)
            # Return error.
            rc = output['rc']
            if rc != "0":
                return output

            userlist = output.get('message')
            role = None
            for userinfo in userlist:
                username = userinfo.split('\t')[0]
                if username == self.user:
                    role = userinfo.split('\t')[1]
                    break

            output['message'] = role
        except Exception as ex:
            if 'show users' in str(ex):
                msg = ("Specified user(%s) does not have Software role"
                       % self.user)
            elif 'Error connecting' in str(ex):
                msg = (str(ex)[34:] +
                       ', Please check fujitsu_private_key_path or .xml file')
            else:
                msg = str(ex)
            output = {
                'result': 0,
                'rc': '4',
                'message': msg
            }
        return output

    def _expand_volume(self, **option):
        """Exec expand volume."""
        return self._exec_cli("expand volume", **option)

    def _set_volume_qos(self, **option):
        """Exec set volume-qos."""
        return self._exec_cli("set volume-qos", **option)

    def _show_pool_provision(self, **option):
        """Get TPP provision capacity information."""
        try:
            output = self._exec_cli("show volumes", **option)

            rc = output['rc']

            if rc != "0":
                return output

            clidatalist = output.get('message')

            data = 0
            for clidataline in clidatalist[1:]:
                clidata = clidataline.split('\t')
                if clidata[0] == 'FFFF':
                    break
                data += int(clidata[7], 16)
            provision = data / 2048

            output['message'] = provision
        except Exception as ex:
            output = {
                'result': 0,
                'rc': '4',
                'message': "show pool provision capacity error: %s" % ex
            }

        return output

    def _show_copy_sessions(self, **option):
        """Get copy sessions."""
        try:
            output = self._exec_cli("show copy-sessions", **option)

            # return error
            rc = output['rc']

            if rc != "0":
                return output

            cpsdatalist = []
            clidatalist = output.get('message')

            for clidataline in clidatalist[1:]:
                clidata = clidataline.split('\t')
                # Get CopyType
                if clidata[2] == '01':
                    # CopyKind: OPC
                    if bin(int(clidata[3], 16) & 16) != 0:
                        # eg. 0b10010000
                        temp_type = 'Snap'
                    elif bin(int(clidata[3], 16) & 64) != 0:
                        # eg. 0b11000000
                        temp_type = 'Snap+'
                    else:
                        temp_type = 'Other'
                elif clidata[2] == '02':
                    # CopyKind: EC
                    if clidata[5] == 'FF':
                        temp_type = 'EC'
                    elif clidata[5] == '10':
                        temp_type = 'Sync_REC'
                    else:
                        temp_type = 'Other'
                else:
                    temp_type = 'Other'

                # Get Phases
                if clidata[6] == '00':
                    temp_phase = 'No_Pair'
                elif clidata[6] == '01':
                    temp_phase = 'Copying'
                elif clidata[6] == '02':
                    temp_phase = 'Equivalent'
                elif clidata[6] == '03':
                    temp_phase = 'Tracking'
                elif clidata[6] == '04':
                    temp_phase = 'Tracking_Copying'
                elif clidata[6] == '06':
                    temp_phase = 'Readying'
                else:
                    temp_phase = 'Other'

                # Get CopyStatus
                if clidata[7] == '00':
                    temp_status = 'Idle'
                elif clidata[7] == '01':
                    temp_status = 'Reserve'
                elif clidata[7] == '02':
                    temp_status = 'Active'
                elif clidata[7] == '03':
                    temp_status = 'Error_Suspend'
                elif clidata[7] == '04':
                    temp_status = 'Suspend'
                elif clidata[7] == '05':
                    temp_status = 'Halt'
                else:
                    temp_status = 'Other'

                cpsdatalist.append({'Source Num': int(clidata[13], 16),
                                    'Dest Num': int(clidata[14], 16),
                                    'Type': temp_type,
                                    'Status': temp_status,
                                    'Phase': temp_phase,
                                    'Session ID': int(clidata[0], 16)})

            output['message'] = cpsdatalist
        except Exception as ex:
            output = {'result': 0,
                      'rc': '4',
                      'message': "Show copy sessions error: %s"
                                 % str(ex)}

        return output

    def _show_qos_bandwidth_limit(self, **option):
        """Get qos bandwidth limit."""
        clidata = None
        try:
            output = self._exec_cli("show qos-bandwidth-limit", **option)

            # return error
            rc = output['rc']

            if rc != "0":
                return output

            qoslist = []
            clidatalist = output.get('message')

            for clidataline in clidatalist[1:]:
                clidata = clidataline.split('\t')
                qoslist.append({'total_limit': int(clidata[0], 16),
                                'total_iops_sec': int(clidata[1], 16),
                                'total_bytes_sec': int(clidata[2], 16),
                                'read_limit': int(clidata[0], 16),
                                'read_iops_sec': int(clidata[3], 16),
                                'read_bytes_sec': int(clidata[4], 16),
                                'write_limit': int(clidata[0], 16),
                                'write_iops_sec': int(clidata[5], 16),
                                'write_bytes_sec': int(clidata[6], 16)})

            output['message'] = qoslist

        except IndexError as ex:
            msg = ('The results returned by cli are not as expected. '
                   'Exception string: %s' % clidata)
            output = {'result': 0,
                      'rc': '4',
                      'message': "Show qos bandwidth limit error: %s. %s"
                                 % (ex, msg)}

        except Exception as ex:
            output = {'result': 0,
                      'rc': '4',
                      'message': "Show qos bandwidth limit error: %s" % ex}

        return output

    def _set_qos_bandwidth_limit(self, **option):
        """Set qos bandwidth limit"""
        return self._exec_cli("set qos-bandwidth-limit", **option)

    def _show_volume_qos(self, **option):
        """Get volumes with qos."""
        clidata = None
        try:
            output = self._exec_cli("show volume-qos", **option)

            # return error
            rc = output['rc']

            if rc != "0":
                return output

            vqosdatalist = []
            clidatalist = output.get('message')

            for clidataline in clidatalist[1:]:
                clidata = clidataline.split('\t')
                vqosdatalist.append({'total_limit': int(clidata[2], 16),
                                     'read_limit': int(clidata[3], 16),
                                     'write_limit': int(clidata[4], 16)})

            output['message'] = vqosdatalist

        except IndexError as ex:
            msg = ('The results returned by cli are not as expected. '
                   'Exception string: %s' % clidata)
            output = {'result': 0,
                      'rc': '4',
                      'message': "Show volume qos error: %s. %s" % (ex, msg)}

        except Exception as ex:
            output = {'result': 0,
                      'rc': '4',
                      'message': "Show volume qos error: %s" % ex}

        return output

    def _show_enclosure_status(self, **option):
        """Get the version of machine."""
        clidata = None
        try:
            output = self._exec_cli("show enclosure-status", **option)

            # return error
            rc = output['rc']

            if rc != "0":
                return output

            clidatalist = output.get('message')
            clidata = clidatalist[0].split('\t')
            versioninfo = {'version': clidata[11]}

            output['message'] = versioninfo

        except IndexError as ex:
            msg = ('The results returned by cli are not as expected. '
                   'Exception string: %s' % clidata)
            output = {'result': 0,
                      'rc': '4',
                      'message': "Show enclosure status error: %s. %s"
                                 % (ex, msg)}

        except Exception as ex:
            output = {'result': 0,
                      'rc': '4',
                      'message': "Show enclosure status error: %s" % ex}

        return output

    def _start_copy_snap_opc(self, **option):
        """Exec start copy-snap-opc."""
        return self._exec_cli("start copy-snap-opc", **option)

    def _stop_copy_session(self, **option):
        """Exec stop copy-session."""
        return self._exec_cli("stop copy-session", **option)

    def _start_copy_opc(self, **option):
        """Exec start copy-opc."""
        return self._exec_cli("start copy-opc", **option)

    def _delete_volume(self, **option):
        """Exec delete volume."""
        return self._exec_cli('delete volume', **option)
