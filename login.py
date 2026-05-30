"""Wechat QR-code login helper for the vendored SDK."""

import os
import sys


def main():
    project_dir = os.path.dirname(os.path.abspath(__file__))
    vendor_dir = os.path.join(project_dir, 'vendor')
    if vendor_dir not in sys.path:
        sys.path.insert(0, vendor_dir)

    from ilinkai_weixin.auth.account_store import AccountStore, WeixinAccountData
    from ilinkai_weixin.auth.qrcode_login_service import QRCodeLoginService
    from ilinkai_weixin.weixin_api_client import DEFAULT_BASE_URL

    login_service = QRCodeLoginService(DEFAULT_BASE_URL)
    print('正在获取登录二维码...')
    start_result = login_service.start_login()
    if not start_result.qr_code_url:
        print('获取二维码失败: %s' % start_result.message)
        return 1

    print('请在浏览器打开或复制到二维码工具显示以下内容，然后用微信扫码：')
    print(start_result.qr_code_url)
    print('等待扫码确认...')

    def on_status(status):
        if status == '.':
            print('.', end='')
            sys.stdout.flush()
        else:
            print(status)

    def on_qr_refreshed(url):
        print('\n二维码已刷新，请使用新内容扫码：')
        print(url)

    wait_result = login_service.wait_for_login(
        start_result.qr_code,
        timeout_ms=300000,
        on_status_changed=on_status,
        on_qr_refreshed=on_qr_refreshed,
    )

    if not wait_result.connected:
        print('\n登录失败: %s' % wait_result.message)
        return 1

    account_store = AccountStore()
    normalized_id = AccountStore.normalize_account_id(wait_result.account_id or '')
    account_store.save_account(normalized_id, WeixinAccountData(
        token=wait_result.bot_token,
        base_url=wait_result.base_url,
        user_id=wait_result.user_id,
    ))
    account_store.register_account_id(normalized_id)

    print('\n登录成功')
    print('账户ID: %s' % normalized_id)
    print('用户ID: %s' % wait_result.user_id)
    print('账号已保存到 ~/.ilinkai')
    return 0


if __name__ == '__main__':
    sys.exit(main())
