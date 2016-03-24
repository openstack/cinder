# Copyright (c) 2016 Clinton Knight
# All rights reserved.
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

NODE = 'cluster1-01'

COUNTERS_T1 = [
    {
        'node-name': 'cluster1-01',
        'instance-uuid': 'cluster1-01:kernel:system',
        'avg_processor_busy': '29078861388',
        'instance-name': 'system',
        'timestamp': '1453573776',
    }, {
        'node-name': 'cluster1-01',
        'instance-uuid': 'cluster1-01:kernel:system',
        'cpu_elapsed_time': '1063283283681',
        'instance-name': 'system',
        'timestamp': '1453573776',
    }, {
        'node-name': 'cluster1-01',
        'instance-uuid': 'cluster1-01:kernel:system',
        'cpu_elapsed_time1': '1063283283681',
        'instance-name': 'system',
        'timestamp': '1453573776',
    }, {
        'cp_phase_times:p2a_snap': '714',
        'cp_phase_times:p4_finish': '14897',
        'cp_phase_times:setup': '581',
        'cp_phase_times:p2a_dlog1': '6019',
        'cp_phase_times:p2a_dlog2': '2328',
        'cp_phase_times:p2v_cont': '2479',
        'cp_phase_times:p2v_volinfo': '1138',
        'cp_phase_times:p2v_bm': '3484',
        'cp_phase_times:p2v_fsinfo': '2031',
        'cp_phase_times:p2a_inofile': '356',
        'cp_phase_times': '581,5007,1840,9832,498,0,839,799,1336,2031,0,377,'
                          '427,1058,354,3484,5135,1460,1138,2479,356,1373'
                          ',6019,9,2328,2257,229,493,1275,0,6059,714,530215,'
                          '21603833,0,0,3286,11075940,22001,14897,36',
        'cp_phase_times:p2v_dlog2': '377',
        'instance-name': 'wafl',
        'cp_phase_times:p3_wait': '0',
        'cp_phase_times:p2a_bm': '6059',
        'cp_phase_times:p1_quota': '498',
        'cp_phase_times:p2v_inofile': '839',
        'cp_phase_times:p2a_refcount': '493',
        'cp_phase_times:p2a_fsinfo': '2257',
        'cp_phase_times:p2a_hyabc': '0',
        'cp_phase_times:p2a_volinfo': '530215',
        'cp_phase_times:pre_p0': '5007',
        'cp_phase_times:p2a_hya': '9',
        'cp_phase_times:p0_snap_del': '1840',
        'cp_phase_times:p2a_ino': '1373',
        'cp_phase_times:p2v_df_scores_sub': '354',
        'cp_phase_times:p2v_ino_pub': '799',
        'cp_phase_times:p2a_ipu_bitmap_grow': '229',
        'cp_phase_times:p2v_refcount': '427',
        'timestamp': '1453573776',
        'cp_phase_times:p2v_dlog1': '0',
        'cp_phase_times:p2_finish': '0',
        'cp_phase_times:p1_clean': '9832',
        'node-name': 'cluster1-01',
        'instance-uuid': 'cluster1-01:kernel:wafl',
        'cp_phase_times:p3a_volinfo': '11075940',
        'cp_phase_times:p2a_topaa': '1275',
        'cp_phase_times:p2_flush': '21603833',
        'cp_phase_times:p2v_df_scores': '1460',
        'cp_phase_times:ipu_disk_add': '0',
        'cp_phase_times:p2v_snap': '5135',
        'cp_phase_times:p5_finish': '36',
        'cp_phase_times:p2v_ino_pri': '1336',
        'cp_phase_times:p3v_volinfo': '3286',
        'cp_phase_times:p2v_topaa': '1058',
        'cp_phase_times:p3_finish': '22001',
    }, {
        'node-name': 'cluster1-01',
        'instance-uuid': 'cluster1-01:kernel:wafl',
        'total_cp_msecs': '33309624',
        'instance-name': 'wafl',
        'timestamp': '1453573776',
    }, {
        'domain_busy:kahuna': '2712467226',
        'timestamp': '1453573777',
        'domain_busy:cifs': '434036',
        'domain_busy:raid_exempt': '28',
        'node-name': 'cluster1-01',
        'instance-uuid': 'cluster1-01:kernel:processor0',
        'domain_busy:target': '6460782',
        'domain_busy:nwk_exempt': '20',
        'domain_busy:raid': '722094140',
        'domain_busy:storage': '2253156562',
        'instance-name': 'processor0',
        'domain_busy:cluster': '34',
        'domain_busy:wafl_xcleaner': '51275254',
        'domain_busy:wafl_exempt': '1243553699',
        'domain_busy:protocol': '54',
        'domain_busy': '1028851855595,2712467226,2253156562,5688808118,'
                       '722094140,28,6460782,59,434036,1243553699,51275254,'
                       '61237441,34,54,11,20,5254181873,13656398235,452215',
        'domain_busy:nwk_legacy': '5254181873',
        'domain_busy:dnscache': '59',
        'domain_busy:exempt': '5688808118',
        'domain_busy:hostos': '13656398235',
        'domain_busy:sm_exempt': '61237441',
        'domain_busy:nwk_exclusive': '11',
        'domain_busy:idle': '1028851855595',
        'domain_busy:ssan_exempt': '452215',
    }, {
        'node-name': 'cluster1-01',
        'instance-uuid': 'cluster1-01:kernel:processor0',
        'processor_elapsed_time': '1063283843318',
        'instance-name': 'processor0',
        'timestamp': '1453573777',
    }, {
        'domain_busy:kahuna': '1978024846',
        'timestamp': '1453573777',
        'domain_busy:cifs': '318584',
        'domain_busy:raid_exempt': '0',
        'node-name': 'cluster1-01',
        'instance-uuid': 'cluster1-01:kernel:processor1',
        'domain_busy:target': '3330956',
        'domain_busy:nwk_exempt': '0',
        'domain_busy:raid': '722235930',
        'domain_busy:storage': '1498890708',
        'instance-name': 'processor1',
        'domain_busy:cluster': '0',
        'domain_busy:wafl_xcleaner': '50122685',
        'domain_busy:wafl_exempt': '1265921369',
        'domain_busy:protocol': '0',
        'domain_busy': '1039557880852,1978024846,1498890708,3734060289,'
                       '722235930,0,3330956,0,318584,1265921369,50122685,'
                       '36417362,0,0,0,0,2815252976,10274810484,393451',
        'domain_busy:nwk_legacy': '2815252976',
        'domain_busy:dnscache': '0',
        'domain_busy:exempt': '3734060289',
        'domain_busy:hostos': '10274810484',
        'domain_busy:sm_exempt': '36417362',
        'domain_busy:nwk_exclusive': '0',
        'domain_busy:idle': '1039557880852',
        'domain_busy:ssan_exempt': '393451',
    }, {
        'node-name': 'cluster1-01',
        'instance-uuid': 'cluster1-01:kernel:processor1',
        'processor_elapsed_time': '1063283843321',
        'instance-name': 'processor1',
        'timestamp': '1453573777',
    }
]

COUNTERS_T2 = [
    {
        'node-name': 'cluster1-01',
        'instance-uuid': 'cluster1-01:kernel:system',
        'avg_processor_busy': '29081228905',
        'instance-name': 'system',
        'timestamp': '1453573834',
    }, {
        'node-name': 'cluster1-01',
        'instance-uuid': 'cluster1-01:kernel:system',
        'cpu_elapsed_time': '1063340792148',
        'instance-name': 'system',
        'timestamp': '1453573834',
    }, {
        'node-name': 'cluster1-01',
        'instance-uuid': 'cluster1-01:kernel:system',
        'cpu_elapsed_time1': '1063340792148',
        'instance-name': 'system',
        'timestamp': '1453573834',
    }, {
        'cp_phase_times:p2a_snap': '714',
        'cp_phase_times:p4_finish': '14897',
        'cp_phase_times:setup': '581',
        'cp_phase_times:p2a_dlog1': '6019',
        'cp_phase_times:p2a_dlog2': '2328',
        'cp_phase_times:p2v_cont': '2479',
        'cp_phase_times:p2v_volinfo': '1138',
        'cp_phase_times:p2v_bm': '3484',
        'cp_phase_times:p2v_fsinfo': '2031',
        'cp_phase_times:p2a_inofile': '356',
        'cp_phase_times': '581,5007,1840,9832,498,0,839,799,1336,2031,0,377,'
                          '427,1058,354,3484,5135,1460,1138,2479,356,1373,'
                          '6019,9,2328,2257,229,493,1275,0,6059,714,530215,'
                          '21604863,0,0,3286,11076392,22001,14897,36',
        'cp_phase_times:p2v_dlog2': '377',
        'instance-name': 'wafl',
        'cp_phase_times:p3_wait': '0',
        'cp_phase_times:p2a_bm': '6059',
        'cp_phase_times:p1_quota': '498',
        'cp_phase_times:p2v_inofile': '839',
        'cp_phase_times:p2a_refcount': '493',
        'cp_phase_times:p2a_fsinfo': '2257',
        'cp_phase_times:p2a_hyabc': '0',
        'cp_phase_times:p2a_volinfo': '530215',
        'cp_phase_times:pre_p0': '5007',
        'cp_phase_times:p2a_hya': '9',
        'cp_phase_times:p0_snap_del': '1840',
        'cp_phase_times:p2a_ino': '1373',
        'cp_phase_times:p2v_df_scores_sub': '354',
        'cp_phase_times:p2v_ino_pub': '799',
        'cp_phase_times:p2a_ipu_bitmap_grow': '229',
        'cp_phase_times:p2v_refcount': '427',
        'timestamp': '1453573834',
        'cp_phase_times:p2v_dlog1': '0',
        'cp_phase_times:p2_finish': '0',
        'cp_phase_times:p1_clean': '9832',
        'node-name': 'cluster1-01',
        'instance-uuid': 'cluster1-01:kernel:wafl',
        'cp_phase_times:p3a_volinfo': '11076392',
        'cp_phase_times:p2a_topaa': '1275',
        'cp_phase_times:p2_flush': '21604863',
        'cp_phase_times:p2v_df_scores': '1460',
        'cp_phase_times:ipu_disk_add': '0',
        'cp_phase_times:p2v_snap': '5135',
        'cp_phase_times:p5_finish': '36',
        'cp_phase_times:p2v_ino_pri': '1336',
        'cp_phase_times:p3v_volinfo': '3286',
        'cp_phase_times:p2v_topaa': '1058',
        'cp_phase_times:p3_finish': '22001',
    }, {
        'node-name': 'cluster1-01',
        'instance-uuid': 'cluster1-01:kernel:wafl',
        'total_cp_msecs': '33311106',
        'instance-name': 'wafl',
        'timestamp': '1453573834',
    }, {
        'domain_busy:kahuna': '2712629374',
        'timestamp': '1453573834',
        'domain_busy:cifs': '434036',
        'domain_busy:raid_exempt': '28',
        'node-name': 'cluster1-01',
        'instance-uuid': 'cluster1-01:kernel:processor0',
        'domain_busy:target': '6461082',
        'domain_busy:nwk_exempt': '20',
        'domain_busy:raid': '722136824',
        'domain_busy:storage': '2253260824',
        'instance-name': 'processor0',
        'domain_busy:cluster': '34',
        'domain_busy:wafl_xcleaner': '51277506',
        'domain_busy:wafl_exempt': '1243637154',
        'domain_busy:protocol': '54',
        'domain_busy': '1028906640232,2712629374,2253260824,5689093500,'
                       '722136824,28,6461082,59,434036,1243637154,51277506,'
                       '61240335,34,54,11,20,5254491236,13657992139,452215',
        'domain_busy:nwk_legacy': '5254491236',
        'domain_busy:dnscache': '59',
        'domain_busy:exempt': '5689093500',
        'domain_busy:hostos': '13657992139',
        'domain_busy:sm_exempt': '61240335',
        'domain_busy:nwk_exclusive': '11',
        'domain_busy:idle': '1028906640232',
        'domain_busy:ssan_exempt': '452215',
    }, {
        'node-name': 'cluster1-01',
        'instance-uuid': 'cluster1-01:kernel:processor0',
        'processor_elapsed_time': '1063341351916',
        'instance-name': 'processor0',
        'timestamp': '1453573834',
    }, {
        'domain_busy:kahuna': '1978217049',
        'timestamp': '1453573834',
        'domain_busy:cifs': '318584',
        'domain_busy:raid_exempt': '0',
        'node-name': 'cluster1-01',
        'instance-uuid': 'cluster1-01:kernel:processor1',
        'domain_busy:target': '3331147',
        'domain_busy:nwk_exempt': '0',
        'domain_busy:raid': '722276805',
        'domain_busy:storage': '1498984059',
        'instance-name': 'processor1',
        'domain_busy:cluster': '0',
        'domain_busy:wafl_xcleaner': '50126176',
        'domain_busy:wafl_exempt': '1266039846',
        'domain_busy:protocol': '0',
        'domain_busy': '1039613222253,1978217049,1498984059,3734279672,'
                       '722276805,0,3331147,0,318584,1266039846,50126176,'
                       '36419297,0,0,0,0,2815435865,10276068104,393451',
        'domain_busy:nwk_legacy': '2815435865',
        'domain_busy:dnscache': '0',
        'domain_busy:exempt': '3734279672',
        'domain_busy:hostos': '10276068104',
        'domain_busy:sm_exempt': '36419297',
        'domain_busy:nwk_exclusive': '0',
        'domain_busy:idle': '1039613222253',
        'domain_busy:ssan_exempt': '393451',
    }, {
        'node-name': 'cluster1-01',
        'instance-uuid': 'cluster1-01:kernel:processor1',
        'processor_elapsed_time': '1063341351919',
        'instance-name': 'processor1',
        'timestamp': '1453573834',
    },
]

SYSTEM_INSTANCE_UUIDS = ['cluster1-01:kernel:system']
SYSTEM_INSTANCE_NAMES = ['system']

SYSTEM_COUNTERS = [
    {
        'node-name': 'cluster1-01',
        'instance-uuid': 'cluster1-01:kernel:system',
        'avg_processor_busy': '27877641199',
        'instance-name': 'system',
        'timestamp': '1453524928',
    }, {
        'node-name': 'cluster1-01',
        'instance-uuid': 'cluster1-01:kernel:system',
        'cpu_elapsed_time': '1014438541279',
        'instance-name': 'system',
        'timestamp': '1453524928',
    }, {
        'node-name': 'cluster1-01',
        'instance-uuid': 'cluster1-01:kernel:system',
        'cpu_elapsed_time1': '1014438541279',
        'instance-name': 'system',
        'timestamp': '1453524928',
    },
]


WAFL_INSTANCE_UUIDS = ['cluster1-01:kernel:wafl']
WAFL_INSTANCE_NAMES = ['wafl']

WAFL_COUNTERS = [
    {
        'cp_phase_times': '563,4844,1731,9676,469,0,821,763,1282,1937,0,359,'
                          '418,1048,344,3344,4867,1397,1101,2380,356,1318,'
                          '5954,9,2236,2190,228,476,1221,0,5838,696,515588,'
                          '20542954,0,0,3122,10567367,20696,13982,36',
        'node-name': 'cluster1-01',
        'instance-uuid': 'cluster1-01:kernel:wafl',
        'instance-name': 'wafl',
        'timestamp': '1453523339',
    }, {
        'node-name': 'cluster1-01',
        'instance-uuid': 'cluster1-01:kernel:wafl',
        'total_cp_msecs': '31721222',
        'instance-name': 'wafl',
        'timestamp': '1453523339',
    },
]

WAFL_CP_PHASE_TIMES_COUNTER_INFO = {
    'labels': [
        'SETUP', 'PRE_P0', 'P0_SNAP_DEL', 'P1_CLEAN', 'P1_QUOTA',
        'IPU_DISK_ADD', 'P2V_INOFILE', 'P2V_INO_PUB', 'P2V_INO_PRI',
        'P2V_FSINFO', 'P2V_DLOG1', 'P2V_DLOG2', 'P2V_REFCOUNT',
        'P2V_TOPAA', 'P2V_DF_SCORES_SUB', 'P2V_BM', 'P2V_SNAP',
        'P2V_DF_SCORES', 'P2V_VOLINFO', 'P2V_CONT', 'P2A_INOFILE',
        'P2A_INO', 'P2A_DLOG1', 'P2A_HYA', 'P2A_DLOG2', 'P2A_FSINFO',
        'P2A_IPU_BITMAP_GROW', 'P2A_REFCOUNT', 'P2A_TOPAA',
        'P2A_HYABC', 'P2A_BM', 'P2A_SNAP', 'P2A_VOLINFO', 'P2_FLUSH',
        'P2_FINISH', 'P3_WAIT', 'P3V_VOLINFO', 'P3A_VOLINFO',
        'P3_FINISH', 'P4_FINISH', 'P5_FINISH',
    ],
    'name': 'cp_phase_times',
}

EXPANDED_WAFL_COUNTERS = [
    {
        'cp_phase_times:p2a_snap': '696',
        'cp_phase_times:p4_finish': '13982',
        'cp_phase_times:setup': '563',
        'cp_phase_times:p2a_dlog1': '5954',
        'cp_phase_times:p2a_dlog2': '2236',
        'cp_phase_times:p2v_cont': '2380',
        'cp_phase_times:p2v_volinfo': '1101',
        'cp_phase_times:p2v_bm': '3344',
        'cp_phase_times:p2v_fsinfo': '1937',
        'cp_phase_times:p2a_inofile': '356',
        'cp_phase_times': '563,4844,1731,9676,469,0,821,763,1282,1937,0,359,'
                          '418,1048,344,3344,4867,1397,1101,2380,356,1318,'
                          '5954,9,2236,2190,228,476,1221,0,5838,696,515588,'
                          '20542954,0,0,3122,10567367,20696,13982,36',
        'cp_phase_times:p2v_dlog2': '359',
        'instance-name': 'wafl',
        'cp_phase_times:p3_wait': '0',
        'cp_phase_times:p2a_bm': '5838',
        'cp_phase_times:p1_quota': '469',
        'cp_phase_times:p2v_inofile': '821',
        'cp_phase_times:p2a_refcount': '476',
        'cp_phase_times:p2a_fsinfo': '2190',
        'cp_phase_times:p2a_hyabc': '0',
        'cp_phase_times:p2a_volinfo': '515588',
        'cp_phase_times:pre_p0': '4844',
        'cp_phase_times:p2a_hya': '9',
        'cp_phase_times:p0_snap_del': '1731',
        'cp_phase_times:p2a_ino': '1318',
        'cp_phase_times:p2v_df_scores_sub': '344',
        'cp_phase_times:p2v_ino_pub': '763',
        'cp_phase_times:p2a_ipu_bitmap_grow': '228',
        'cp_phase_times:p2v_refcount': '418',
        'timestamp': '1453523339',
        'cp_phase_times:p2v_dlog1': '0',
        'cp_phase_times:p2_finish': '0',
        'cp_phase_times:p1_clean': '9676',
        'node-name': 'cluster1-01',
        'instance-uuid': 'cluster1-01:kernel:wafl',
        'cp_phase_times:p3a_volinfo': '10567367',
        'cp_phase_times:p2a_topaa': '1221',
        'cp_phase_times:p2_flush': '20542954',
        'cp_phase_times:p2v_df_scores': '1397',
        'cp_phase_times:ipu_disk_add': '0',
        'cp_phase_times:p2v_snap': '4867',
        'cp_phase_times:p5_finish': '36',
        'cp_phase_times:p2v_ino_pri': '1282',
        'cp_phase_times:p3v_volinfo': '3122',
        'cp_phase_times:p2v_topaa': '1048',
        'cp_phase_times:p3_finish': '20696',
    }, {
        'node-name': 'cluster1-01',
        'instance-uuid': 'cluster1-01:kernel:wafl',
        'total_cp_msecs': '31721222',
        'instance-name': 'wafl',
        'timestamp': '1453523339',
    },
]

PROCESSOR_INSTANCE_UUIDS = [
    'cluster1-01:kernel:processor0',
    'cluster1-01:kernel:processor1',
]
PROCESSOR_INSTANCE_NAMES = ['processor0', 'processor1']

PROCESSOR_COUNTERS = [
    {
        'node-name': 'cluster1-01',
        'instance-uuid': 'cluster1-01:kernel:processor0',
        'domain_busy': '980648687811,2597164534,2155400686,5443901498,'
                       '690280568,28,6180773,59,413895,1190100947,48989575,'
                       '58549809,34,54,11,20,5024141791,13136260754,452215',
        'instance-name': 'processor0',
        'timestamp': '1453524150',
    }, {
        'node-name': 'cluster1-01',
        'instance-uuid': 'cluster1-01:kernel:processor0',
        'processor_elapsed_time': '1013660714257',
        'instance-name': 'processor0',
        'timestamp': '1453524150',
    }, {
        'node-name': 'cluster1-01',
        'instance-uuid': 'cluster1-01:kernel:processor1',
        'domain_busy': '990957980543,1891766637,1433411516,3572427934,'
                       '691372324,0,3188648,0,305947,1211235777,47954620,'
                       '34832715,0,0,0,0,2692084482,9834648927,393451',
        'instance-name': 'processor1',
        'timestamp': '1453524150',
    }, {
        'node-name': 'cluster1-01',
        'instance-uuid': 'cluster1-01:kernel:processor1',
        'processor_elapsed_time': '1013660714261',
        'instance-name': 'processor1',
        'timestamp': '1453524150',
    },
]

PROCESSOR_DOMAIN_BUSY_COUNTER_INFO = {
    'labels': [
        'idle', 'kahuna', 'storage', 'exempt', 'raid', 'raid_exempt',
        'target', 'dnscache', 'cifs', 'wafl_exempt', 'wafl_xcleaner',
        'sm_exempt', 'cluster', 'protocol', 'nwk_exclusive', 'nwk_exempt',
        'nwk_legacy', 'hostOS', 'ssan_exempt',
    ],
    'name': 'domain_busy',
}

EXPANDED_PROCESSOR_COUNTERS = [
    {
        'domain_busy:kahuna': '2597164534',
        'timestamp': '1453524150',
        'domain_busy:cifs': '413895',
        'domain_busy:raid_exempt': '28',
        'node-name': 'cluster1-01',
        'instance-uuid': 'cluster1-01:kernel:processor0',
        'domain_busy:target': '6180773',
        'domain_busy:nwk_exempt': '20',
        'domain_busy:raid': '690280568',
        'domain_busy:storage': '2155400686',
        'instance-name': 'processor0',
        'domain_busy:cluster': '34',
        'domain_busy:wafl_xcleaner': '48989575',
        'domain_busy:wafl_exempt': '1190100947',
        'domain_busy:protocol': '54',
        'domain_busy': '980648687811,2597164534,2155400686,5443901498,'
                       '690280568,28,6180773,59,413895,1190100947,48989575,'
                       '58549809,34,54,11,20,5024141791,13136260754,452215',
        'domain_busy:nwk_legacy': '5024141791',
        'domain_busy:dnscache': '59',
        'domain_busy:exempt': '5443901498',
        'domain_busy:hostos': '13136260754',
        'domain_busy:sm_exempt': '58549809',
        'domain_busy:nwk_exclusive': '11',
        'domain_busy:idle': '980648687811',
        'domain_busy:ssan_exempt': '452215',
    }, {
        'node-name': 'cluster1-01',
        'instance-uuid': 'cluster1-01:kernel:processor0',
        'processor_elapsed_time': '1013660714257',
        'instance-name': 'processor0',
        'timestamp': '1453524150',
    }, {
        'domain_busy:kahuna': '1891766637',
        'timestamp': '1453524150',
        'domain_busy:cifs': '305947',
        'domain_busy:raid_exempt': '0',
        'node-name': 'cluster1-01',
        'instance-uuid': 'cluster1-01:kernel:processor1',
        'domain_busy:target': '3188648',
        'domain_busy:nwk_exempt': '0',
        'domain_busy:raid': '691372324',
        'domain_busy:storage': '1433411516',
        'instance-name': 'processor1',
        'domain_busy:cluster': '0',
        'domain_busy:wafl_xcleaner': '47954620',
        'domain_busy:wafl_exempt': '1211235777',
        'domain_busy:protocol': '0',
        'domain_busy': '990957980543,1891766637,1433411516,3572427934,'
                       '691372324,0,3188648,0,305947,1211235777,47954620,'
                       '34832715,0,0,0,0,2692084482,9834648927,393451',
        'domain_busy:nwk_legacy': '2692084482',
        'domain_busy:dnscache': '0',
        'domain_busy:exempt': '3572427934',
        'domain_busy:hostos': '9834648927',
        'domain_busy:sm_exempt': '34832715',
        'domain_busy:nwk_exclusive': '0',
        'domain_busy:idle': '990957980543',
        'domain_busy:ssan_exempt': '393451',
    }, {
        'node-name': 'cluster1-01',
        'instance-uuid': 'cluster1-01:kernel:processor1',
        'processor_elapsed_time': '1013660714261',
        'instance-name': 'processor1',
        'timestamp': '1453524150',
    },
]
