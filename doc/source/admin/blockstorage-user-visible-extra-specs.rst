.. _user_visible_extra_specs:

========================
User visible extra specs
========================

Starting in Xena, certain volume type ``extra specs`` (i.e. properties) are
considered user visible, meaning their visibility is not restricted to only
cloud administrators. This feature provides regular users with more
information about the volume types available to them, and lets them make more
informed decisions on which volume type to choose when creating volumes.

The following ``extra spec`` keys are treated as user visible:

- ``RESKEY:availability_zones``
- ``multiattach``
- ``replication_enabled``

.. note::

   * The set of user visible ``extra specs`` is a fixed list that is not
     configurable.

   * The feature is entirely policy based, and does not require a new
     microversion.

Behavior using openstack client
-------------------------------

Consider the following volume type, as viewed from an administrator's
perspective. In this example, ``multiattach`` is a user visible ``extra spec``
and ``volume_backend_name`` is not.

.. code-block:: console

   # Administrator behavior
   [admin@host]$ openstack volume type show vol_type
   +--------------------+-------------------------------------------------------+
   | Field              | Value                                                 |
   +--------------------+-------------------------------------------------------+
   | access_project_ids | None                                                  |
   | description        | None                                                  |
   | id                 | d03a0f33-e695-4f5c-b712-7d92abbf72be                  |
   | is_public          | True                                                  |
   | name               | vol_type                                              |
   | properties         | multiattach='<is> True', volume_backend_name='secret' |
   | qos_specs_id       | None                                                  |
   +--------------------+-------------------------------------------------------+

Here is the output when a regular user executes the same command. Notice only
the user visible ``multiattach`` property is listed.

.. code-block:: console

   # Regular user behavior
   [user@host]$ openstack volume type show vol_type
   +--------------------+--------------------------------------+
   | Field              | Value                                |
   +--------------------+--------------------------------------+
   | access_project_ids | None                                 |
   | description        | None                                 |
   | id                 | d03a0f33-e695-4f5c-b712-7d92abbf72be |
   | is_public          | True                                 |
   | name               | vol_type                             |
   | properties         | multiattach='<is> True'              |
   +--------------------+--------------------------------------+

The behavior for listing volume types is similar. Administrators will see all
``extra specs`` but regular users will see only user visible ``extra specs``.

.. code-block:: console

   # Administrator behavior
   [admin@host]$ openstack volume type list --long
   +--------------------------------------+-------------+-----------+---------------------+-------------------------------------------------------+
   | ID                                   | Name        | Is Public | Description         | Properties                                            |
   +--------------------------------------+-------------+-----------+---------------------+-------------------------------------------------------+
   | d03a0f33-e695-4f5c-b712-7d92abbf72be | vol_type    | True      | None                | multiattach='<is> True', volume_backend_name='secret' |
   | 80f38273-f4b9-4862-a4e6-87692eb66a96 | __DEFAULT__ | True      | Default Volume Type |                                                       |
   +--------------------------------------+-------------+-----------+---------------------+-------------------------------------------------------+

   # Regular user behavior
   [user@host]$ openstack volume type list --long
   +--------------------------------------+-------------+-----------+---------------------+-------------------------+
   | ID                                   | Name        | Is Public | Description         | Properties              |
   +--------------------------------------+-------------+-----------+---------------------+-------------------------+
   | d03a0f33-e695-4f5c-b712-7d92abbf72be | vol_type    | True      | None                | multiattach='<is> True' |
   | 80f38273-f4b9-4862-a4e6-87692eb66a96 | __DEFAULT__ | True      | Default Volume Type |                         |
   +--------------------------------------+-------------+-----------+---------------------+-------------------------+

Regular users may view these properties, but they may not modify them. Attempts
to modify a user visible property by a non-administrator will fail.

.. code-block:: console

   [user@host]$ openstack volume type set --property multiattach='<is> False' vol_type
   Failed to set volume type property: Policy doesn't allow
   volume_extension:types_extra_specs:create to be performed. (HTTP 403)

Filtering with extra specs
--------------------------

API microversion 3.52 adds support for using ``extra specs`` to filter the
list of volume types. Regular users are able to use that feature to filter for
user visible ``extra specs``. If a regular user attempts to filter on a
non-user visible ``extra spec`` then an empty list is returned.

.. code-block:: console

   # Administrator behavior
   [admin@host]$ cinder --os-volume-api-version 3.52 type-list \
   > --filters extra_specs={"multiattach":"<is> True"}
   +--------------------------------------+----------+-------------+-----------+
   | ID                                   | Name     | Description | Is_Public |
   +--------------------------------------+----------+-------------+-----------+
   | d03a0f33-e695-4f5c-b712-7d92abbf72be | vol_type | -           | True      |
   +--------------------------------------+----------+-------------+-----------+

   [admin@host]$ cinder --os-volume-api-version 3.52 type-list \
   > --filters extra_specs={"volume_backend_name":"secret"}
   +--------------------------------------+----------+-------------+-----------+
   | ID                                   | Name     | Description | Is_Public |
   +--------------------------------------+----------+-------------+-----------+
   | d03a0f33-e695-4f5c-b712-7d92abbf72be | vol_type | -           | True      |
   +--------------------------------------+----------+-------------+-----------+

   # Regular user behavior
   [user@host]$ cinder --os-volume-api-version 3.52 type-list \
   > --filters extra_specs={"multiattach":"<is> True"}
   +--------------------------------------+----------+-------------+-----------+
   | ID                                   | Name     | Description | Is_Public |
   +--------------------------------------+----------+-------------+-----------+
   | d03a0f33-e695-4f5c-b712-7d92abbf72be | vol_type | -           | True      |
   +--------------------------------------+----------+-------------+-----------+

   [user@host]$ cinder --os-volume-api-version 3.52 type-list \
   > --filters extra_specs={"volume_backend_name":"secret"}
   +----+------+-------------+-----------+
   | ID | Name | Description | Is_Public |
   +----+------+-------------+-----------+
   +----+------+-------------+-----------+

Security considerations
-----------------------

Cloud administrators who do not wish to expose any ``extra specs`` to regular
users may restore the previous behavior by setting the following policies to
their pre-Xena default values.

.. code-block:: console

   "volume_extension:access_types_extra_specs": "rule:admin_api"
   "volume_extension:types_extra_specs:index": "rule:admin_api"
   "volume_extension:types_extra_specs:show": "rule:admin_api"

To restrict regular users from using ``extra specs`` to filter the list of
volume types, modify /etc/cinder/resource_filters.json to restore the
*"volume_type"* entry to its pre-Xena default value.

.. code-block:: console

   "volume_type": ["is_public"]
