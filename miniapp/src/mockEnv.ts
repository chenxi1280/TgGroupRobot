import { emitEvent, isTMA, mockTelegramEnv } from '@tma.js/sdk-react';

if (import.meta.env.DEV && !await isTMA('complete')) {
  const scene = new URLSearchParams(location.search).get('scene') || 'verify_preview';
  const theme = { bg_color: '#ffffff', text_color: '#203b34', hint_color: '#7a8984', secondary_bg_color: '#f4f7f6', button_color: '#18876c', button_text_color: '#ffffff' } as const;
  mockTelegramEnv({
    launchParams: new URLSearchParams({
      tgWebAppVersion: '8.0', tgWebAppPlatform: 'tdesktop', tgWebAppThemeParams: JSON.stringify(theme),
      tgWebAppData: new URLSearchParams({ auth_date: `${Math.floor(Date.now() / 1000)}`, hash: 'development-only', signature: 'development-only', user: JSON.stringify({ id: 42, first_name: '测试用户' }), start_param: scene }).toString(),
    }),
    onEvent(event) {
      if (event.name === 'web_app_request_theme') emitEvent('theme_changed', { theme_params: theme });
    },
  });
}
