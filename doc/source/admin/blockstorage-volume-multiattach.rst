.. _volume_multiattach:

==================================================================
Volume multi-attach: Enable attaching a volume to multiple servers
==================================================================

The ability to attach a volume to multiple hosts/servers simultaneously is a
use case desired for active/active or active/standby scenarios.

Support was added in both `Cinder`_ and `Nova`_ in the Queens release to volume
multi-attach with read/write (RW) mode.

.. warning::

   It is the responsibility of the user to ensure that a multiattach or
   clustered file system is used on the volumes. Otherwise there may be a high
   probability of data corruption.

In Cinder the functionality is available from microversion '3.50' or higher.

As a prerequisite `new Attach/Detach APIs were added to Cinder`_ in Ocata to
overcome earlier limitations towards achieving volume multi-attach.

In case you use Cinder together with Nova, compute API calls were switched to
using the new block storage volume attachment APIs in Queens, if the required
block storage API microversion is available.

For more information on using multiattach volumes with the compute service,
refer to the corresponding
`compute admin guide section <https://docs.openstack.org/nova/latest/admin/manage-volumes.html#volume-multi-attach>`_.

How to create a 'multiattach' volume
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In order to be able to attach a volume to multiple server instances you need to
have the 'multiattach' flag set to 'True' in the volume details. Please ensure
you have the right role and policy settings before performing the operation.

Currently you can create a multiattach volume in two ways.

.. note::

   For information on back ends that provide the functionality see
   `Back end support`.

Multiattach volume type
-----------------------

Starting from the Queens release the ability to attach a volume to multiple
hosts/servers requires that the volume is of a special type that includes an
extra-spec capability setting of ``multiattach=<is> True``. You can create the
volume type the following way:

.. code-block:: console

   $ cinder type-create multiattach
   $ cinder type-key multiattach set multiattach="<is> True"

.. note::

   Creating a new volume type is an admin-only operation by default, you can
   change the settings in the 'policy.json' configuration file if needed.

To create the volume you need to use the volume type you created earlier, like
this:

.. code-block:: console

   $ cinder create <volume_size> --name <volume_name> --volume-type <volume_type_uuid>

In addition, it is possible to retype a volume to be (or not to be) multiattach
capable. Currently however we only allow retyping a volume if its status is
``available``.

The reasoning behind the limitation is that some consumers/hypervisors need to
make special considerations at attach-time for multiattach volumes (like
disable caching) and there's no mechanism currently to update a currently
attached volume in a safe way while keeping it attached the whole time.

RO / RW caveats (the secondary RW attachment issue)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

By default, secondary volume attachments are made in read/write mode
which can be problematic, especially for operations like volume migration.

There might be improvements to provide support to specify the attach-mode for
the secondary attachments, for the latest information please take a look into
`Cinder's specs list`_ for the current release.

Back end support
~~~~~~~~~~~~~~~~

In order to have the feature available, multi-attach needs to be supported by
the chosen back end which is indicated through capabilities in the
corresponding volume driver.

The reference implementation is available on LVM in the Queens release. You can
check the :ref:`Driver Support Matrix <driver_support_matrix>` for further
information on which back end provides the functionality.

Policy rules
~~~~~~~~~~~~

You can control the availability of volume multi-attach through policies. We
describe the default values in this documentation, you need to modify the
'policy.json' configuration file if you would like to changes these settings.

Multiattach policy
------------------

The general policy rule to allow the creation or retyping of multiattach
volumes is named  ``volume:multiattach``.

The default setting of this policy is ``rule:admin_or_owner``.

Multiattach policy for bootable volumes
---------------------------------------

This is a policy to disallow the ability to create multiple attachments on a
volume that is marked as bootable with the name
``volume:multiattach_bootable_volume``.

This is an attachment policy with a default setting of ``rule:admin_or_owner``.

Known issues and limitations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Retyping an in-use volume from a multiattach-capable type to a
  non-multiattach-capable type, or vice-versa, is not supported.
- It is not recommended to retype an in-use multiattach volume if that volume
  has more than one active read/write attachment.
- Encryption is not supported with multiattach-capable volumes.

.. _`Cinder`: https://specs.openstack.org/openstack/cinder-specs/specs/queens/enable-multiattach.html
.. _`Nova`: https://specs.openstack.org/openstack/nova-specs/specs/queens/approved/cinder-volume-multi-attach.html
.. _`new Attach/Detach APIs were added to Cinder`: http://specs.openstack.org/openstack/cinder-specs/specs/ocata/add-new-attach-apis.html
.. _`Cinder's specs list`: https://specs.openstack.org/openstack/cinder-specs/index.html
