"""
Methods to allow for compatibility with v4 of the Fuel Rats API

Copyright (c) 2019 The Fuel Rats Mischief,
All rights reserved.

Licensed under the BSD 3-Clause License.

See LICENSE.md
"""

"""
I'm sorry.
"""


def convertv3DataTov2(v3Data, single=False):
    print('Incoming v3 Data: ' + str(v3Data))
    ret = []
    if single:
        v3Data = [v3Data]
    for case in v3Data:
        v2Data = case
        v2Data['attributes']['id'] = case['id']
        if case['relationships']['firstLimpet']['data']:
            v2Data['attributes']['firstLimpetId'] = case['relationships']['firstLimpet']['data']['id']
        ret.append(v2Data)
    return ret


def convertv2RescueTov3(v2Rescue):
    v3Rescue = {'data': {'type': 'rescues', 'attributes': v2Rescue}}
    if 'id' in v2Rescue:
        v3Rescue['data']['id'] = v2Rescue['id']
        del v3Rescue['data']['attributes']['id']
    if 'firstLimpetId' in v2Rescue:
        if not v2Rescue['firstLimpetId']:
            v3Rescue['data']['relationships']['firstLimpet'] = {'data': None}
        else:
            v3Rescue['data']['relationships']['firstLimpet'] =\
                {'data': {'type': 'rats', 'id': v2Rescue['firstLimpetId']}}
        del v3Rescue['data']['attributes']['firstLimpetId']
    return v3Rescue
