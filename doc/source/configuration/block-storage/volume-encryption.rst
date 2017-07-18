==============================================
Volume encryption supported by the key manager
==============================================

We recommend the Key management service (barbican) for storing
encryption keys used by the OpenStack volume encryption feature. It can
be enabled by updating ``cinder.conf`` and ``nova.conf``.

Initial configuration
~~~~~~~~~~~~~~~~~~~~~

Configuration changes need to be made to any nodes running the
``cinder-api`` or ``nova-compute`` server.

Steps to update ``cinder-api`` servers:

#. Edit the ``/etc/cinder/cinder.conf`` file to use Key management service
   as follows:

   * Look for the ``[key_manager]`` section.

   * Enter a new line directly below ``[key_manager]`` with the following:

     .. code-block:: ini

        api_class = castellan.key_manager.barbican_key_manager.BarbicanKeyManager

#. Restart ``cinder-api``.

Update ``nova-compute`` servers:

#. Ensure the ``cryptsetup`` utility is installed, and install
   the ``python-barbicanclient`` Python package.

#. Set up the Key Manager service by editing ``/etc/nova/nova.conf``:

   .. code-block:: ini

      [key_manager]
      api_class = castellan.key_manager.barbican_key_manager.BarbicanKeyManager

     .. note::

        Use a '#' prefix to comment out the line in this section that
        begins with 'fixed_key'.

#. Restart ``nova-compute``.


Key management access control
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Special privileges can be assigned on behalf of an end user to allow
them to manage their own encryption keys, which are required when
creating the encrypted volumes. The Barbican `Default Policy
<https://docs.openstack.org/developer/barbican/admin-guide-cloud/access_control.html#default-policy>`_
for access control specifies that only users with an ``admin`` or
``creator`` role can create keys. The policy is very flexible and
can be modified.

To assign the ``creator`` role, the admin must know the user ID,
project ID, and creator role ID. See `Assign a role
<https://docs.openstack.org/admin-guide/cli-manage-projects-users-and-roles.html#assign-a-role>`_
for more information. An admin can list existing roles and associated
IDs using the ``openstack role list`` command. If the creator
role does not exist, the admin can `create the role
<https://docs.openstack.org/admin-guide/cli-manage-projects-users-and-roles.html#create-a-role>`_.


Create an encrypted volume type
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Block Storage volume type assignment provides scheduling to a specific
back-end, and can be used to specify actionable information for a
back-end storage device.

This example creates a volume type called LUKS and provides
configuration information for the storage system to encrypt or decrypt
the volume.

#. Source your admin credentials:

   .. code-block:: console

      $ . admin-openrc.sh

#. Create the volume type, marking the volume type as encrypted and providing
   the necessary details. Use ``--encryption-control-location`` to specify
   where encryption is performed: ``front-end`` (default) or ``back-end``.

   .. code-block:: console

      $ openstack volume type create --encryption-provider nova.volume.encryptors.luks.LuksEncryptor \
        --encryption-cipher aes-xts-plain64 --encryption-key-size 256 --encryption-control-location front-end LUKS

        +-------------+----------------------------------------------------------------+
        | Field       | Value                                                          |
        +-------------+----------------------------------------------------------------+
        | description | None                                                           |
        | encryption  | cipher='aes-xts-plain64', control_location='front-end',        |
        |             | encryption_id='8584c43f-1666-43d1-a348-45cfcef72898',          |
        |             | key_size='256',                                                |
        |             | provider='nova.volume.encryptors.luks.LuksEncryptor'           |
        | id          | b9a8cff5-2f60-40d1-8562-d33f3bf18312                           |
        | is_public   | True                                                           |
        | name        | LUKS                                                           |
        +-------------+----------------------------------------------------------------+

The OpenStack dashboard (horizon) supports creating the encrypted
volume type as of the Kilo release. For instructions, see
`Create an encrypted volume type
<https://docs.openstack.org/admin-guide/dashboard-manage-volumes.html>`_.

Create an encrypted volume
~~~~~~~~~~~~~~~~~~~~~~~~~~

Use the OpenStack dashboard (horizon), or :command:`openstack volume
create` command to create volumes just as you normally would. For an
encrypted volume, pass the ``--type LUKS`` flag, which specifies that the
volume type will be ``LUKS`` (Linux Unified Key Setup). If that argument is
left out, the default volume type, ``unencrypted``, is used.

#. Source your admin credentials:

   .. code-block:: console

      $ . admin-openrc.sh

#. Create an unencrypted 1 GB test volume:

   .. code-block:: console


      $ openstack volume create --size 1 'unencrypted volume'


#. Create an encrypted 1 GB test volume:

   .. code-block:: console

      $ openstack volume create --size 1 --type LUKS 'encrypted volume'

Notice the encrypted parameter; it will show ``True`` or ``False``.
The option ``volume_type`` is also shown for easy review.

Non-admin users need the ``creator`` role to store secrets in Barbican
and to create encrypted volumes. As an administrator, you can give a user
the creator role in the following way:

.. code-block:: console

   $ openstack role add --project PROJECT --user USER creator

For details, see the
`Barbican Access Control page
<https://docs.openstack.org/developer/barbican/admin-guide-cloud/access_control.html>`_.

.. note::

   Due to the issue that some of the volume drivers do not set
   ``encrypted`` flag, attaching of encrypted volumes to a virtual
   guest will fail, because OpenStack Compute service will not run
   encryption providers.

Testing volume encryption
~~~~~~~~~~~~~~~~~~~~~~~~~

This is a simple test scenario to help validate your encryption. It
assumes an LVM based Block Storage server.

Perform these steps after completing the volume encryption setup and
creating the volume-type for LUKS as described in the preceding
sections.

#. Create a VM:

   .. code-block:: console

      $ openstack server create --image cirros-0.3.1-x86_64-disk --flavor m1.tiny TESTVM

#. Create two volumes, one encrypted and one not encrypted then attach them
   to your VM:

   .. code-block:: console

      $ openstack volume create --size 1 'unencrypted volume'
      $ openstack volume create --size 1 --type LUKS 'encrypted volume'
      $ openstack volume list
      $ openstack server add volume --device /dev/vdb TESTVM 'unencrypted volume'
      $ openstack server add volume --device /dev/vdc TESTVM 'encrypted volume'

#. On the VM, send some text to the newly attached volumes and synchronize
   them:

   .. code-block:: console

      # echo "Hello, world (unencrypted /dev/vdb)" >> /dev/vdb
      # echo "Hello, world (encrypted /dev/vdc)" >> /dev/vdc
      # sync && sleep 2
      # sync && sleep 2

#. On the system hosting cinder volume services, synchronize to flush the
   I/O cache then test to see if your strings can be found:

   .. code-block:: console

      # sync && sleep 2
      # sync && sleep 2
      # strings /dev/stack-volumes/volume-* | grep "Hello"
      Hello, world (unencrypted /dev/vdb)

In the above example you see that the search returns the string
written to the unencrypted volume, but not the encrypted one.
