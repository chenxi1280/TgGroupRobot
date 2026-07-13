const verificationTimeoutParams = () => {
  const chatId = $('verificationTimeoutChatId').value.trim()
  if (!chatId) throw new Error('请输入群组 ID')
  const params = new URLSearchParams({ chat_id: chatId, limit: '100' })
  const status = $('verificationTimeoutStatus').value
  if (status) params.set('status', status)
  return params
}

const verificationTimeoutActions = (item) => {
  const primary = item.status === 'uncertain'
    ? `<button class="verification-timeout-action ghost" data-action="replay" data-id="${item.id}">确认重放</button>`
    : `<button class="verification-timeout-action ghost" data-action="retry" data-id="${item.id}">重试</button>`
  return `${primary}<button class="verification-timeout-action ghost" data-action="cancel" data-id="${item.id}">关闭</button>`
}

const loadVerificationTimeouts = async () => {
  try {
    const response = await api(`/admin/api/verification-timeouts?${verificationTimeoutParams()}`)
    $('verificationTimeoutBody').innerHTML = (response.data.items || []).map((item) => `
      <tr>
        <td>${escapeHtml(item.id)}</td>
        <td>${escapeHtml(item.user_id)}</td>
        <td>${escapeHtml(item.status)}</td>
        <td>${escapeHtml(item.action || '')}</td>
        <td>${escapeHtml(item.attempts)}</td>
        <td>${escapeHtml(item.last_error || '')}</td>
        <td>${escapeHtml(formatTime(item.completed_at))}</td>
        <td class="actions">${verificationTimeoutActions(item)}</td>
      </tr>
    `).join('')
  } catch (error) {
    toast(error.message)
  }
}

const confirmVerificationTimeoutReplay = (challengeId) => window.confirm(
  `任务 #${challengeId} 的 Telegram 结果不确定。请确认已人工核对，仍要重放吗？`,
)

const executeVerificationTimeoutAction = async (challengeId, action) => {
  if (action === 'replay' && !confirmVerificationTimeoutReplay(challengeId)) return
  const chatId = $('verificationTimeoutChatId').value.trim()
  const body = action === 'replay' ? JSON.stringify({ confirm: true }) : '{}'
  await api(`/admin/api/verification-timeouts/${challengeId}/${action}?chat_id=${encodeURIComponent(chatId)}`, {
    method: 'POST',
    body,
  })
  toast('操作已保存')
  await loadVerificationTimeouts()
}

$('loadVerificationTimeoutsBtn').addEventListener('click', loadVerificationTimeouts)
$('refreshVerificationTimeoutsBtn').addEventListener('click', loadVerificationTimeouts)
$('verificationTimeoutBody').addEventListener('click', async (event) => {
  const button = event.target.closest('.verification-timeout-action')
  if (!button) return
  try {
    await executeVerificationTimeoutAction(button.dataset.id, button.dataset.action)
  } catch (error) {
    toast(error.message)
  }
})
