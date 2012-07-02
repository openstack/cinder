===========
cinder-manage
===========

------------------------------------------------------
control and manage cloud computer instances and images
------------------------------------------------------

:Author: openstack@lists.launchpad.net
:Date:   2012-04-05
:Copyright: OpenStack LLC
:Version: 2012.1
:Manual section: 1
:Manual group: cloud computing

SYNOPSIS
========

  cinder-manage <category> <action> [<args>]

DESCRIPTION
===========

cinder-manage controls cloud computing instances by managing cinder users, cinder projects, cinder roles, shell selection, vpn connections, and floating IP address configuration. More information about OpenStack Cinder is at http://cinder.openstack.org.

OPTIONS
=======

The standard pattern for executing a cinder-manage command is:
``cinder-manage <category> <command> [<args>]``

For example, to obtain a list of all projects:
``cinder-manage project list``

Run without arguments to see a list of available command categories:
``cinder-manage``

Categories are user, project, role, shell, vpn, and floating. Detailed descriptions are below.

You can also run with a category argument such as user to see a list of all commands in that category:
``cinder-manage user``

These sections describe the available categories and arguments for cinder-manage.

Cinder Db
~~~~~~~

``cinder-manage db version``

    Print the current database version.

``cinder-manage db sync``

    Sync the database up to the most recent version. This is the standard way to create the db as well.

Cinder User
~~~~~~~~~

``cinder-manage user admin <username>``

    Create an admin user with the name <username>.

``cinder-manage user create <username>``

    Create a normal user with the name <username>.

``cinder-manage user delete <username>``

    Delete the user with the name <username>.

``cinder-manage user exports <username>``

    Outputs a list of access key and secret keys for user to the screen

``cinder-manage user list``

    Outputs a list of all the user names to the screen.

``cinder-manage user modify <accesskey> <secretkey> <admin?T/F>``

    Updates the indicated user keys, indicating with T or F if the user is an admin user. Leave any argument blank if you do not want to update it.

Cinder Project
~~~~~~~~~~~~

``cinder-manage project add <projectname>``

    Add a cinder project with the name <projectname> to the database.

``cinder-manage project create <projectname>``

    Create a new cinder project with the name <projectname> (you still need to do cinder-manage project add <projectname> to add it to the database).

``cinder-manage project delete <projectname>``

    Delete a cinder project with the name <projectname>.

``cinder-manage project environment <projectname> <username>``

    Exports environment variables for the named project to a file named cinderrc.

``cinder-manage project list``

    Outputs a list of all the projects to the screen.

``cinder-manage project quota <projectname>``

    Outputs the size and specs of the project's instances including gigabytes, instances, floating IPs, volumes, and cores.

``cinder-manage project remove <projectname>``

    Deletes the project with the name <projectname>.

``cinder-manage project zipfile``

    Compresses all related files for a created project into a zip file cinder.zip.

Cinder Role
~~~~~~~~~

``cinder-manage role add <username> <rolename> <(optional) projectname>``

    Add a user to either a global or project-based role with the indicated <rolename> assigned to the named user. Role names can be one of the following five roles: cloudadmin, itsec, sysadmin, netadmin, developer. If you add the project name as the last argument then the role is assigned just for that project, otherwise the user is assigned the named role for all projects.

``cinder-manage role has <username> <projectname>``
    Checks the user or project and responds with True if the user has a global role with a particular project.

``cinder-manage role remove <username> <rolename>``
    Remove the indicated role from the user.

Cinder Logs
~~~~~~~~~

``cinder-manage logs errors``

    Displays cinder errors from log files.

``cinder-manage logs syslog <number>``

    Displays cinder alerts from syslog.

Cinder Shell
~~~~~~~~~~

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

Cinder VPN
~~~~~~~~

``cinder-manage vpn list``

    Displays a list of projects, their IP prot numbers, and what state they're in.

``cinder-manage vpn run <projectname>``

    Starts the VPN for the named project.

``cinder-manage vpn spawn``

    Runs all VPNs.

Cinder Floating IPs
~~~~~~~~~~~~~~~~~

``cinder-manage floating create <ip_range> [--pool <pool>] [--interface <interface>]``

    Creates floating IP addresses for the given range, optionally specifying
    a floating pool and a network interface.

``cinder-manage floating delete <ip_range>``

    Deletes floating IP addresses in the range given.

``cinder-manage floating list``

    Displays a list of all floating IP addresses.

Cinder Flavor
~~~~~~~~~~~

``cinder-manage flavor list``

    Outputs a list of all active flavors to the screen.

``cinder-manage flavor list --all``

    Outputs a list of all flavors (active and inactive) to the screen.

``cinder-manage flavor create <name> <memory> <vCPU> <local_storage> <flavorID> <(optional) swap> <(optional) RXTX Quota> <(optional) RXTX Cap>``

    creates a flavor with the following positional arguments:
     * memory (expressed in megabytes)
     * vcpu(s) (integer)
     * local storage (expressed in gigabytes)
     * flavorid (unique integer)
     * swap space (expressed in megabytes, defaults to zero, optional)
     * RXTX quotas (expressed in gigabytes, defaults to zero, optional)
     * RXTX cap (expressed in gigabytes, defaults to zero, optional)

``cinder-manage flavor delete <name>``

    Delete the flavor with the name <name>. This marks the flavor as inactive and cannot be launched. However, the record stays in the database for archival and billing purposes.

``cinder-manage flavor delete <name> --purge``

    Purges the flavor with the name <name>. This removes this flavor from the database.

Cinder Instance_type
~~~~~~~~~~~~~~~~~~

The instance_type command is provided as an alias for the flavor command. All the same subcommands and arguments from cinder-manage flavor can be used.

Cinder Images
~~~~~~~~~~~

``cinder-manage image image_register <path> <owner>``

    Registers an image with the image service.

``cinder-manage image kernel_register <path> <owner>``

    Registers a kernel with the image service.

``cinder-manage image ramdisk_register <path> <owner>``

    Registers a ramdisk with the image service.

``cinder-manage image all_register <image_path> <kernel_path> <ramdisk_path> <owner>``

    Registers an image kernel and ramdisk with the image service.

``cinder-manage image convert <directory>``

    Converts all images in directory from the old (Bexar) format to the new format.

Cinder VM
~~~~~~~~~~~

``cinder-manage vm list [host]``
    Show a list of all instances. Accepts optional hostname (to show only instances on specific host).

``cinder-manage live-migration <ec2_id> <destination host name>``
    Live migrate instance from current host to destination host. Requires instance id (which comes from euca-describe-instance) and destination host name (which can be found from cinder-manage service list).


FILES
========

The cinder-manage.conf file contains configuration information in the form of python-gflags.

SEE ALSO
========

* `OpenStack Cinder <http://cinder.openstack.org>`__
* `OpenStack Swift <http://swift.openstack.org>`__

BUGS
====

* Cinder is sourced in Launchpad so you can view current bugs at `OpenStack Cinder <http://cinder.openstack.org>`__



