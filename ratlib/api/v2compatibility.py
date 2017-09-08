"""
Methods to allow for compatibility with v2 of the Fuel Rats API

Copyright (c) 2017 The Fuel Rats Mischief,
All rights reserved.

Licensed under the BSD 3-Clause License.

See LICENSE.md
"""
def convertV2DataToV1(v2Data, single=False):
    newdata = []
    # print("Converting New Data: " + str(v2Data))
    if single:
        v2Data = [v2Data]
    for case in v2Data:
        oldobj = {}
        attr = case['attributes']
        oldobj['id'] = case['id']
        oldobj['active'] = attr['status'] == "open"
        oldobj['client'] = attr['client']
        oldobj['codeRed'] = attr['codeRed']
        oldobj['data'] = attr['data']
        oldobj['open'] = attr['status'] != "closed"
        oldobj['notes'] = attr['notes']
        oldobj['platform'] = attr['platform']
        oldobj['quotes'] = attr['quotes']
        oldobj['success'] = attr['outcome'] == "success"
        oldobj['system'] = attr['system']
        oldobj['title'] = attr['title']
        oldobj['unidentifiedRats'] = attr['unidentifiedRats']
        oldobj['createdAt'] = attr['createdAt']
        oldobj['updatedAt'] = attr['updatedAt']
        oldobj['epic'] = False
        oldobj['firstLimpet'] = attr['firstLimpetId']

        oldobj['rats'] = []
        try:
            for ratid in case['relationships']['rats']['data']:
                oldobj['rats'].append(ratid['id'])
        except:
            pass
        # print("Converted apiv2 object to apiv1 object: in:\n{v2}\nout:\n{v1}".format(v2=str(case), v1=str(oldobj)))
        newdata.append(oldobj)
    return newdata

def convertV1RescueToV2(v1Rescue):
    v2obj = {}
    # print(str(v1Rescue))
    if 'id' in v1Rescue.keys():
        v2obj['id'] = v1Rescue['id']
    if 'client' in v1Rescue.keys():
        v2obj['client'] = v1Rescue['client']
    if 'data' in v1Rescue.keys():
        v2obj['data'] = v1Rescue['data']
    if 'notes' in v1Rescue.keys():
        v2obj['notes'] = v1Rescue['notes']
    if 'system' in v1Rescue.keys():
        v2obj['system'] = v1Rescue['system']
    if 'firstLimpet' in v1Rescue.keys():
        v2obj['firstLimpetId'] = v1Rescue['firstLimpet'] if v1Rescue['firstLimpet'] != "" else None
    if 'unidentifiedRats' in v1Rescue.keys():
        v2obj['unidentifiedRats'] = v1Rescue['unidentifiedRats']
    if 'platform' in v1Rescue.keys():
        v2obj['platform'] = v1Rescue['platform']
    if 'quotes' in v1Rescue.keys():
        v2obj['quotes'] = v1Rescue['quotes']
    if 'codeRed' in v1Rescue.keys():
        v2obj['codeRed'] = v1Rescue['codeRed']

    if 'success' in v1Rescue.keys():
        v2obj['outcome'] = "success" if v1Rescue['success'] else "failure"


    if 'open' in v1Rescue.keys() or 'active' in v1Rescue.keys():
        if 'open' not in v1Rescue.keys():
            v2obj['status'] = "open" if v1Rescue['active'] else "inactive"
        elif 'active' not in v1Rescue.keys():
            v2obj['status'] = "open" if v1Rescue['open'] else "closed"
        elif not v1Rescue['open']:
            v2obj['status'] = "closed"
        elif not v1Rescue['active']:
            v2obj['status'] = "inactive"
        else:
            v2obj['status'] = "open"


    return v2obj
