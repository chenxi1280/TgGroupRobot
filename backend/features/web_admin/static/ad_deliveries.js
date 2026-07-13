const adDeliveryParams = () => {
  const chatId = $('adDeliveryChatId').value.trim()
  if (!chatId) throw new Error('请输入群组 ID')
  const params = new URLSearchParams({ chat_id: chatId, limit: '100' })
  const status = $('adDeliveryStatus').value
  if (status) params.set('status', status)
  return params
}

const adDeliveryActions = (item) => {
  if (['retryable_failed', 'permanent_failed'].includes(item.status)) {
    return `<button class="ad-delivery-action ghost" data-action="retry" data-id="${item.id}">重试</button>
      <button class="ad-delivery-action ghost" data-action="cancel" data-id="${item.id}">取消</button>`
  }
  if (item.status === 'uncertain') {
    return `<button class="ad-delivery-action ghost" data-action="replay" data-id="${item.id}">确认重放</button>
      <button class="ad-delivery-action ghost" data-action="cancel" data-id="${item.id}">取消</button>`
  }
  return ''
}

const loadAdDeliveries = async () => {
  try {
    const response = await api(`/admin/api/ad-deliveries?${adDeliveryParams()}`)
    $('adDeliveriesBody').innerHTML = (response.data.items || []).map((item) => `
      <tr>
        <td>${escapeHtml(item.id)}</td>
        <td>${escapeHtml(item.title || item.campaign_id || '')}</td>
        <td>${escapeHtml(item.status)}</td>
        <td>${escapeHtml(item.attempts)}</td>
        <td>${escapeHtml(item.error || '')}</td>
        <td>${escapeHtml(formatTime(item.scheduled_for))}</td>
        <td>${escapeHtml(formatTime(item.next_retry_at))}</td>
        <td class="actions">${adDeliveryActions(item)}</td>
      </tr>
    `).join('')
  } catch (error) {
    toast(error.message)
  }
}

const executeAdDeliveryAction = async (historyId, action) => {
  const chatId = $('adDeliveryChatId').value.trim()
  let body = '{}'
  if (action === 'replay') {
    if (!window.confirm(`派发 #${historyId} 的结果不确定，确认承担重复广告风险并重放吗？`)) return
    const reason = window.prompt('请输入本次人工重放原因')?.trim()
    if (!reason) throw new Error('人工重放必须填写原因')
    body = JSON.stringify({ confirm: true, reason })
  }
  await api(`/admin/api/ad-deliveries/${historyId}/${action}?chat_id=${encodeURIComponent(chatId)}`, {
    method: 'POST',
    body,
  })
  toast('操作已保存')
  await loadAdDeliveries()
}

$('loadAdDeliveriesBtn').addEventListener('click', loadAdDeliveries)
$('refreshAdDeliveriesBtn').addEventListener('click', loadAdDeliveries)
$('adDeliveriesBody').addEventListener('click', async (event) => {
  const button = event.target.closest('.ad-delivery-action')
  if (!button) return
  try {
    await executeAdDeliveryAction(button.dataset.id, button.dataset.action)
  } catch (error) {
    toast(error.message)
  }
})
