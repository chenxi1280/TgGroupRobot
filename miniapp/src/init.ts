import { backButton, initData, init as initSDK, miniApp, themeParams } from '@tma.js/sdk-react';

export function init(): void {
  initSDK();
  initData.restore();
  if (!initData.raw()) throw new Error('请从 Telegram 机器人消息中的按钮打开');
  if (miniApp.mount.isAvailable()) {
    themeParams.mount();
    miniApp.mount();
    themeParams.bindCssVars();
  }
  backButton.mount.ifAvailable();
  backButton.onClick.ifAvailable(() => miniApp.close());
  miniApp.ready.ifAvailable();
}
