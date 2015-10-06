#!/usr/bin/env python
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import subprocess

if __name__ == "__main__":
    opt_file = open("cinder/opts.py", 'a')
    opt_dict = {}
    dir_trees_list = []
    REGISTER_OPTS_STR = "CONF.register_opts("
    REGISTER_OPT_STR = "CONF.register_opt("

    opt_file.write("import copy\n")
    opt_file.write("import itertools\n\n")

    targetdir = os.environ['TARGETDIR']
    basedir = os.environ['BASEDIRESC']

    common_string = ('find ' + targetdir + ' -type f -name "*.py" !  '
                     '-path "*/tests/*" -exec grep -l "%s" {} '
                     '+  | sed -e "s/^' + basedir +
                     '\///g" | sort -u')

    cmd_opts = common_string % REGISTER_OPTS_STR
    output_opts = subprocess.check_output('{}'.format(cmd_opts), shell = True)
    dir_trees_list = output_opts.split()

    cmd_opt = common_string % REGISTER_OPT_STR
    output_opt = subprocess.check_output('{}'.format(cmd_opt), shell = True)
    temp_list = output_opt.split()

    for item in temp_list:
        dir_trees_list.append(item)
    dir_trees_list.sort()

    flag = False

    for atree in dir_trees_list:

        if atree in ["cinder/config/generate_cinder_opts.py",
                     "cinder/hacking/checks.py"]:
            continue

        dirs_list = atree.split('/')

        import_module = "from "
        init_import_module = ""
        import_name = ""

        for dir in dirs_list:
            if dir.find(".py") == -1:
                import_module += dir + "."
                init_import_module += dir + "."
                import_name += dir + "_"
            else:
                if dir[:-3] != "__init__":
                    import_name += dir[:-3].replace("_", "")
                    import_module = (import_module[:-1] + " import " +
                                     dir[:-3] + " as " + import_name)
                    opt_file.write(import_module + "\n")
                else:
                    import_name = import_name[:-1].replace('/', '.')
                    init_import = atree[:-12].replace('/', '.')
                    opt_file.write("import " + init_import + "\n")
                    flag = True
        if flag is False:
            opt_dict[import_name] = atree
        else:
            opt_dict[init_import_module.strip(".")] = atree

        flag = False

    registered_opts_dict = {'fc-zone-manager': [],
                            'keymgr': [],
                            'BRCD_FABRIC_EXAMPLE': [],
                            'CISCO_FABRIC_EXAMPLE': [],
                            'profiler': [],
                            'backend': [],
                            'DEFAULT': [], }

    def _write_item(opts):
        list_name = opts[-3:]
        if list_name.lower() == "opt":
            opt_file.write("            [" + opts.strip("\n") + "],\n")
        else:
            opt_file.write("            " + opts.strip("\n") + ",\n")

    def _retrieve_name(aline):
        if REGISTER_OPT_STR in aline:
            str_to_replace = REGISTER_OPT_STR
        else:
            str_to_replace = REGISTER_OPTS_STR
        return aline.replace(str_to_replace, "")

    for key in opt_dict:
        fd = os.open(opt_dict[key], os.O_RDONLY)
        afile = os.fdopen(fd, "r")

        for aline in afile:
            exists = aline.find("CONF.register_opt")
            if exists != -1:
                # TODO(kjnelson) FIX THIS LATER. These are instances where
                # CONF.register_opts is happening without actually registering
                # real lists of opts

                exists = aline.find('base_san_opts')
                if (exists != -1) or (key == 'cinder_volume_configuration'):
                    continue

                if aline.find("fc-zone-manager") != -1:
                    fc_zm_list = _retrieve_name(aline)
                    replace_string = ", group='fc-zone-manager')"
                    fc_zm_list = fc_zm_list.replace(replace_string, '')
                    fc_zm_list = fc_zm_list.strip()
                    line = key + "." + fc_zm_list
                    registered_opts_dict['fc-zone-manager'].append(line)
                elif aline.find("keymgr") != -1:
                    keymgr_list = _retrieve_name(aline)
                    keymgr_list = keymgr_list.replace(", group='keymgr')", '')
                    keymgr_list = keymgr_list.strip()
                    line = key + "." + keymgr_list
                    registered_opts_dict['keymgr'].append(line)
                elif aline.find("BRCD_FABRIC_EXAMPLE") != -1:
                    brcd_list = _retrieve_name(aline)
                    replace_string = ", group='BRCD_FABRIC_EXAMPLE')"
                    brcd_list = brcd_list.replace(replace_string, '')
                    brcd_list = brcd_list.strip()
                    line = key + "." + brcd_list
                    registered_opts_dict['BRCD_FABRIC_EXAMPLE'].append(line)
                elif aline.find("CISCO_FABRIC_EXAMPLE") != -1:
                    cisco_list = _retrieve_name(aline)
                    replace_string = ", group='CISCO_FABRIC_EXAMPLE')"
                    cisco_list = cisco_list.replace(replace_string, '')
                    cisco_list = cisco_list.strip()
                    line = key + "." + cisco_list
                    registered_opts_dict['CISCO_FABRIC_EXAMPLE'].append(line)
                elif aline.find("profiler") != -1:
                    profiler_list = _retrieve_name(aline)
                    replace_string = ', group="profiler")'
                    profiler_list = profiler_list.replace(replace_string, '')
                    profiler_list = profiler_list.strip()
                    line = key + "." + profiler_list
                    registered_opts_dict['profiler'].append(line)
                elif aline.find("backend") != -1:
                    backend_list = _retrieve_name(aline)
                    replace_string = ', group=backend)'
                    backend_list = backend_list.replace(replace_string, '')
                    backend_list = backend_list.strip()
                    line = key + "." + backend_list
                    registered_opts_dict['backend'].append(line)
                else:
                    default_list = _retrieve_name(aline)
                    default_list = default_list.replace(')', '').strip()
                    line = key + "." + default_list
                    registered_opts_dict['DEFAULT'].append(line)
        opt_dict[key] = registered_opts_dict

    list_str = ("def list_opts():\n"
                "    return [\n"
                "        ('DEFAULT',\n"
                "        itertools.chain(\n")
    opt_file.write(list_str)

    for item in registered_opts_dict["DEFAULT"]:
        _write_item(item)

    profiler_str = ("    )),\n"
                    "    ('profiler',\n"
                    "    itertools.chain(\n")
    opt_file.write(profiler_str)

    for item in registered_opts_dict["profiler"]:
        _write_item(item)

    backend_str = ("    )),\n"
                   "    ('backend',\n"
                   "    itertools.chain(\n")
    opt_file.write(backend_str)

    for item in registered_opts_dict["backend"]:
        _write_item(item)

    cisco_str = ("    )),\n"
                 "    ('CISCO_FABRIC_EXAMPLE',\n"
                 "    itertools.chain(\n")
    opt_file.write(cisco_str)

    for item in registered_opts_dict["CISCO_FABRIC_EXAMPLE"]:
        _write_item(item)

    brcd_str = ("    )),\n"
                "    ('BRCD_FABRIC_EXAMPLE',\n"
                "    itertools.chain(\n")
    opt_file.write(brcd_str)

    for item in registered_opts_dict["BRCD_FABRIC_EXAMPLE"]:
        _write_item(item)

    keymgr_str = ("    )),\n"
                  "    ('keymgr',\n"
                  "    itertools.chain(\n")
    opt_file.write(keymgr_str)

    for item in registered_opts_dict["keymgr"]:
        _write_item(item)

    fczm_str = ("    )),\n"
                "    ('fc-zone-manager',\n"
                "    itertools.chain(\n")
    opt_file.write(fczm_str)

    for item in registered_opts_dict["fc-zone-manager"]:
        _write_item(item)

    closing_str = ("    )),\n"
                   "]\n\n\n")
    opt_file.write(closing_str)
    opt_file.close()
