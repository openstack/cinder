.. -*- rst -*-

Quota sets extension (os-quota-sets)
====================================

Administrators only, depending on policy settings.

Shows, updates, and deletes quotas for a tenant.


Show quota details for user (v1)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v1/{admin_tenant_id}/os-quota-sets/{tenant_id}/detail/{user_id}

Shows details for quotas for a tenant and user.

Normal response codes: 200
Error response codes:

Request
-------

.. rest_parameters:: parameters.yaml

   - admin_tenant_id: admin_tenant_id
   - tenant_id: tenant_id
   - user_id: user_id


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - injected_file_content_bytes: injected_file_content_bytes
   - metadata_items: metadata_items
   - reserved: reserved
   - in_use: in_use
   - ram: ram
   - floating_ips: floating_ips
   - key_pairs: key_pairs
   - injected_file_path_bytes: injected_file_path_bytes
   - instances: instances
   - limit: limit
   - security_group_rules: security_group_rules
   - injected_files: injected_files
   - quota_set: quota_set
   - cores: cores
   - fixed_ips: fixed_ips
   - id: id
   - security_groups: security_groups

Response Example
----------------

.. literalinclude:: ./samples/user-quotas-show-detail-response.json
   :language: javascript

Show default quotas
~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v1/{tenant_id}/os-quota-sets/defaults

Shows default quotas for a tenant.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - injected_file_content_bytes: injected_file_content_bytes
   - metadata_items: metadata_items
   - reserved: reserved
   - in_use: in_use
   - ram: ram
   - floating_ips: floating_ips
   - key_pairs: key_pairs
   - injected_file_path_bytes: injected_file_path_bytes
   - instances: instances
   - security_group_rules: security_group_rules
   - injected_files: injected_files
   - quota_set: quota_set
   - cores: cores
   - fixed_ips: fixed_ips
   - id: id
   - security_groups: security_groups

Response Example
----------------

.. literalinclude:: ./samples/quotas-defaults-show-response.json
   :language: javascript


Show quotas (v1)
~~~~~~~~~~~~~~~~

.. rest_method::  GET /v1/{admin_tenant_id}/os-quota-sets/{tenant_id}

Shows quotas for a tenant.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - admin_tenant_id: admin_tenant_id
   - tenant_id: tenant_id
   - usage: usage


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - injected_file_content_bytes: injected_file_content_bytes
   - metadata_items: metadata_items
   - reserved: reserved
   - in_use: in_use
   - ram: ram
   - floating_ips: floating_ips
   - key_pairs: key_pairs
   - injected_file_path_bytes: injected_file_path_bytes
   - instances: instances
   - security_group_rules: security_group_rules
   - injected_files: injected_files
   - quota_set: quota_set
   - cores: cores
   - fixed_ips: fixed_ips
   - id: id
   - security_groups: security_groups


Response Example
----------------

.. literalinclude:: ./samples/quotas-show-response.json
   :language: javascript


Update quotas (v1)
~~~~~~~~~~~~~~~~~~

.. rest_method::  PUT /v1/{admin_tenant_id}/os-quota-sets/{tenant_id}

Updates quotas for a tenant.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - injected_file_content_bytes: injected_file_content_bytes
   - metadata_items: metadata_items
   - ram: ram
   - floating_ips: floating_ips
   - key_pairs: key_pairs
   - id: id
   - instances: instances
   - security_group_rules: security_group_rules
   - injected_files: injected_files
   - quota_set: quota_set
   - cores: cores
   - fixed_ips: fixed_ips
   - injected_file_path_bytes: injected_file_path_bytes
   - security_groups: security_groups
   - admin_tenant_id: admin_tenant_id
   - tenant_id: tenant_id

Request Example
---------------

.. literalinclude:: ./samples/quotas-update-request.json
   :language: javascript



Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - injected_file_content_bytes: injected_file_content_bytes
   - metadata_items: metadata_items
   - reserved: reserved
   - in_use: in_use
   - ram: ram
   - floating_ips: floating_ips
   - key_pairs: key_pairs
   - injected_file_path_bytes: injected_file_path_bytes
   - instances: instances
   - security_group_rules: security_group_rules
   - injected_files: injected_files
   - quota_set: quota_set
   - cores: cores
   - fixed_ips: fixed_ips
   - id: id
   - security_groups: security_groups

Response Example
----------------

.. literalinclude:: ./samples/quotas-update-response.json
   :language: javascript


Delete quotas (v1)
~~~~~~~~~~~~~~~~~~

.. rest_method::  DELETE /v1/{admin_tenant_id}/os-quota-sets/{tenant_id}

Deletes quotas for a tenant so the quotas revert to default values.

Normal response codes: 200
Error response codes:

Request
-------

.. rest_parameters:: parameters.yaml

   - admin_tenant_id: admin_tenant_id
   - tenant_id: tenant_id

Response Example
----------------

.. literalinclude:: ./samples/user-quotas-delete-response.json
   :language: javascript

Show quotas for user (v1)
~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v1/{admin_tenant_id}/os-quota-sets/{tenant_id}/{user_id}

Enables an admin user to show quotas for a tenant and user.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - admin_tenant_id: admin_tenant_id
   - tenant_id: tenant_id
   - user_id: user_id


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - injected_file_content_bytes: injected_file_content_bytes
   - metadata_items: metadata_items
   - reserved: reserved
   - in_use: in_use
   - ram: ram
   - floating_ips: floating_ips
   - key_pairs: key_pairs
   - injected_file_path_bytes: injected_file_path_bytes
   - instances: instances
   - security_group_rules: security_group_rules
   - injected_files: injected_files
   - quota_set: quota_set
   - cores: cores
   - fixed_ips: fixed_ips
   - id: id
   - security_groups: security_groups



Response Example
----------------

.. literalinclude:: ./samples/user-quotas-show-response.json
   :language: javascript




Update quotas for user (v1)
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  POST /v1/{admin_tenant_id}/os-quota-sets/{tenant_id}/{user_id}

Updates quotas for a tenant and user.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - injected_file_content_bytes: injected_file_content_bytes
   - metadata_items: metadata_items
   - ram: ram
   - floating_ips: floating_ips
   - key_pairs: key_pairs
   - id: id
   - instances: instances
   - security_group_rules: security_group_rules
   - injected_files: injected_files
   - quota_set: quota_set
   - cores: cores
   - fixed_ips: fixed_ips
   - injected_file_path_bytes: injected_file_path_bytes
   - security_groups: security_groups
   - admin_tenant_id: admin_tenant_id
   - tenant_id: tenant_id
   - user_id: user_id

Request Example
---------------

.. literalinclude:: ./samples/user-quotas-update-request.json
   :language: javascript



Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - injected_file_content_bytes: injected_file_content_bytes
   - metadata_items: metadata_items
   - reserved: reserved
   - in_use: in_use
   - ram: ram
   - floating_ips: floating_ips
   - key_pairs: key_pairs
   - injected_file_path_bytes: injected_file_path_bytes
   - instances: instances
   - security_group_rules: security_group_rules
   - injected_files: injected_files
   - quota_set: quota_set
   - cores: cores
   - fixed_ips: fixed_ips
   - id: id
   - security_groups: security_groups

Response Example
----------------

.. literalinclude:: ./samples/user-quotas-update-response.json
   :language: javascript


Delete quotas for user (v1)
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rest_method::  DELETE /v1/{admin_tenant_id}/os-quota-sets/{tenant_id}/{user_id}

Deletes quotas for a user so that the quotas revert to default values.


Normal response codes: 200
Error response codes:

Request
-------

.. rest_parameters:: parameters.yaml

   - admin_tenant_id: admin_tenant_id
   - tenant_id: tenant_id
   - user_id: user_id


Response Example
----------------

.. literalinclude:: ./samples/user-quotas-delete-response.json
   :language: javascript
