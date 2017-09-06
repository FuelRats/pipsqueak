"""
MEthods to allow for compatibility with v2 of the Fuel Rats API

Copyright (c) 2017 The Fuel Rats Mischief,
All rights reserved.

Licensed under the BSD 3-Clause License.

See LICENSE.md
"""
def convertV2DataToV1(v2Data):
    newdata = []
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
        for ratid in case['relationships']['rats']['data']:
            oldobj['rats'].append(ratid['id'])

        # print("Converted apiv2 object to apiv1 object: in:\n{v2}\nout:\n{v1}".format(v2=str(case), v1=str(oldobj)))
        newdata.append(oldobj)
