import json

import requests


def crm_pay_front_user_deposit(crm_headers, amount="100", login=-1, login_id=-1, mt4=False, mt5=False):
    """
    crm 电汇入金 钱包入金
    :param crm_headers:
    :param login:
    :param amount:
    :param base_amount:
    :return:
    """
    url = 'https://mt5-gate.wetradefx.info' + "/pay/front/userDeposit"
    post_data = {
        "wireReceivingInfoId": 11,
        "depositAccountType": 1,
        "login": login,
        "loginId": login_id,
        "platformName": -1,
        "amount": amount,
        "remark": "",
        "wireVoucherUrl": "https://img.wdcmall.com/customer/96/07/92ec91031f0301a2146b653132013a2a"
    }
    if login != -1:
        post_data["depositAccountType"] = 0
        if mt4 is True:
            post_data["platformName"] = "MT4"
        elif mt5 is True:
            post_data["platformName"] = "MT5"
        else:
            print("未选择mt4 or mt5，platformName传参为空")
            post_data["platformName"] = ""
    res = requests.post(url, headers=crm_headers, json=post_data)
    print("入金：", json.dumps(res.json()))
    deposit_id = res.json()["data"]
    return deposit_id
