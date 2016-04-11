Generation of Sample Configuration Options
==========================================

opts.py
-------
This file is dynamically created through the following commands and is used
in the generation of the cinder.conf.sample file by the oslo config generator.
It is kept in tree because deployers cannot run tox -e genconfig due to
dependency issues. To generate this file only, use the command 'tox -e genopts'.
To generate the cinder.conf.sample file use the command 'tox -e genconfig'.

tox -e genconfig
----------------
This command will generate a new cinder.conf.sample file by running the
cinder/tools/config/generate_sample.sh script.

tox -e genopts
--------------
This command dynamically generates the opts.py file only in the
event that new configuration options have been added. To do this it
runs the generate_sample.sh with the --nosamplefile option.

check_uptodate.sh
-----------------
This script will check that the opts.py file exists and if it does, it
will then create a temp opts.py file to verify that the current opts.py
file is up to date with all new configuration options that may have been
added. If it is not up to date it will suggest the generation of a new
file using 'tox -e genopts'.

generate_sample.sh
------------------
This script is responsible for calling the generate_cinder_opts.py file
which dynamically generates the opts.py file by parsing through the entire
cinder project.  All instances of CONF.register_opt() and CONF.register_opts()
are collected and the needed arguments are pulled out of those methods. A
list of the options being registered is created to be written to the opts.py file.
Later, the oslo config generator takes in the opts.py file, parses through
those lists and creates the sample file.