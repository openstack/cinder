=============
cinder-manage
=============

------------------------------------------------------
Control and manage OpenStack block storage
------------------------------------------------------

:Author: openstack@lists.openstack.org
:Date:   2013-05-30
:Copyright: OpenStack Foundation
:Version: 2013.2
:Manual section: 1
:Manual group: cloud computing

SYNOPSIS
========

  cinder-manage <category> <action> [<args>]

DESCRIPTION
===========

cinder-manage provides control of cinder database migration, and provides an interface to get information about the current state of cinder.  More information about OpenStack Cinder is available at http://cinder.openstack.org.

OPTIONS
=======

The standard pattern for executing a cinder-manage command is:
``cinder-manage <category> <command> [<args>]``

For example, to obtain a list of the cinder services currently running:
``cinder-manage service list``

Run without arguments to see a list of available command categories:
``cinder-manage``

Categories are shell, logs, migrate, db, volume, host, service, backup, version, sm and config. Detailed descriptions are below.

You can also run with a category argument such as 'db' to see a list of all commands in that category:
``cinder-manage db``

These sections describe the available categories and arguments for cinder-manage.

Cinder Db
~~~~~~~~~

``cinder-manage db version``

    Print the current database version.

``cinder-manage db sync``

    Sync the database up to the most recent version. This is the standard way to create the db as well.

``cinder-manage db purge [<number of days>]``

    Purge database entries that are marked as deleted, that are older than the number of days specified.


Cinder Logs
~~~~~~~~~~~

``cinder-manage logs errors``

    Displays cinder errors from log files.

``cinder-manage logs syslog [<number>]``

    Displays cinder the most recent entries from syslog.  The optional number argument specifies the number of entries to display (default 10).

Cinder Shell
~~~~~~~~~~~~

``cinder-manage shell bpython``

    Starts a new bpython shell.

``cinder-manage shell ipython``

    Starts a new ipython shell.

``cinder-manage shell python``

    Starts a new python shell.

``cinder-manage shell run``

    Starts a new shell using python.

``cinder-manage shell script <path/scriptname>``

    Runs the named script from the specified path with flags set.

Cinder Volume
~~~~~~~~~~~~~

``cinder-manage volume reattach <volume_id>``

    Re-attach a volume that has previously been attached to an instance.

``cinder-manage volume delete <volume_id>``

    Delete a volume without first checking that the volume is available.

Cinder Host
~~~~~~~~~~~

``cinder-manage host list [<zone>]``

    Displays a list of all physical hosts and their zone.  The optional zone argument allows the list to be filtered on the requested zone.

Cinder Service
~~~~~~~~~~~~~~

``cinder-manage service list``

    Displays a list of all cinder services and their host, zone, status, state and when the information was last updated.

Cinder Backup
~~~~~~~~~~~~~

``cinder-manage backup list``

    Displays a list of all backups (including ones in progress) and the host on which the backup operation is running.

Cinder Version
~~~~~~~~~~~~~~

``cinder-manage version list``

    Displays the codebase version cinder is running upon.

Cinder Storage Management
~~~~~~~~~~~~~~~~~~~~~~~~~

``cinder-manage sm flavor_create <label> <desc>``

    Creates a Storage Management flavor with the requested label and description.

``cinder-manage sm flavor_list [<flavor id>]``

    Displays a list of all available flavors.  The optional flavor ID parameter may be used to display information for a specific flavor.

``cinder-manage sm flavor_delete <label>``

    Deletes the requested flavor.

``cinder-manage sm backend_add <flavor_label> <sr_type> [<config connection parameters>]``

    Creates a backend using the requested flavor, sr_type and optional arguments.

``cinder-manage sm backend_list [<backend_conf_id>]``

    Displays a list of all backends.  The optional backend ID parameter may be used to display information for a specific backend.

``cinder-manage sm backend_remove <backend_conf_id>``

    Removes the specified backend.

Cinder Config
~~~~~~~~~~~~~

``cinder-manage config list [<param>]``

    Displays the current configuration parameters (options) for Cinder. The optional flag parameter may be used to display the configuration of one parameter.

FILES
=====

The cinder.conf file contains configuration information in the form of python-gflags.

The cinder-manage.log file logs output from cinder-manage.

SEE ALSO
========

* `OpenStack Cinder <http://cinder.openstack.org>`__

BUGS
====

* Cinder is hosted on Launchpad so you can view current bugs at `Bugs : Cinder <https://bugs.launchpad.net/cinder/>`__
