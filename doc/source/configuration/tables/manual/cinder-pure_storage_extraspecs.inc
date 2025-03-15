.. list-table:: Description of extra specs options for Pure Storage FlashArray
   :header-rows: 1

   * - Extra spec
     - Type
     - Description
   * - ``flasharray:vg_name``
     - String
     - Specify the name of the volume group in which all volumes using this
       volume type will be created.
   * - ``flasharray:vg_maxIOPS``
     - String
     - Maximum number of IOPs allowed for the volume group. Range 100 - 100M
   * - ``flasharray:vg_maxBWS``
     - String
     - Maximum bandwidth limit for the volume group. Range 1024 - 524288 (512GB/s)
