const state = {
  specs: [],
  copyLimit: 40,
  cards: [],
  generatedText: '',
  currentAdminId: null,
}

const $ = (id) => document.getElementById(id)

const show = (element, visible) => {
  element.classList.toggle('hidden', !visible)
}

const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
})[char])

const toast = (message) => {
  const box = $('toast')
  box.textContent = message
  show(box, true)
  window.clearTimeout(box._timer)
  box._timer = window.setTimeout(() => show(box, false), 3200)
}

const api = async (url, options = {}) => {
  const response = await fetch(url, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  if (!response.ok) {
    let detail = `请求失败：${response.status}`
    try {
      const body = await response.json()
      detail = body.detail || body.message || detail
    } catch {
      // Keep the default detail.
    }
    throw new Error(detail)
  }
  return response.json()
}

const copyText = async (text) => {
  if (!text) throw new Error('复制内容为空')
  if (window.isSecureContext && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return
    } catch {
      // Fall back to textarea copy for local HTTP and mobile webviews.
    }
  }
  const textArea = document.createElement('textarea')
  textArea.value = text
  textArea.setAttribute('readonly', 'true')
  textArea.style.position = 'fixed'
  textArea.style.left = '-9999px'
  textArea.style.top = '0'
  document.body.appendChild(textArea)
  const activeElement = document.activeElement
  textArea.focus()
  textArea.select()
  textArea.setSelectionRange(0, textArea.value.length)
  const ok = document.execCommand('copy')
  document.body.removeChild(textArea)
  if (activeElement instanceof HTMLElement) activeElement.focus()
  if (!ok) throw new Error('浏览器拒绝复制，请手动选择文本复制')
}

const fillSpecSelects = () => {
  const options = state.specs.map((item) => `<option value="${item.days}">${item.label}</option>`).join('')
  $('specSelect').innerHTML = options
  $('filterSpec').innerHTML = `<option value="">全部规格</option>${options}`
  $('copyLimitHint').textContent = `单次复制 ${state.copyLimit} 条`
}

const currentFilters = () => {
  const params = new URLSearchParams()
  if ($('filterSpec').value) params.set('spec_days', $('filterSpec').value)
  if ($('filterStatus').value) params.set('status', $('filterStatus').value)
  if ($('filterKeyword').value.trim()) params.set('keyword', $('filterKeyword').value.trim())
  params.set('limit', '200')
  return params
}

const renderCards = (items) => {
  state.cards = items
  $('selectAllCards').checked = false
  show($('cardsEmpty'), items.length === 0)
  $('cardsBody').innerHTML = items.map((card) => {
    const status = card.voided
      ? '<span class="status-used">已作废</span>'
      : (card.used ? '<span class="status-used">已激活</span>' : '<span class="status-free">可用</span>')
    const disabled = card.has_plaintext && !card.used && !card.voided ? '' : 'disabled'
    return `
      <tr>
        <td><input class="card-check" type="checkbox" value="${escapeHtml(card.id)}" ${disabled}></td>
        <td class="code">${escapeHtml(card.card_code || '历史卡密无明文')}</td>
        <td>${escapeHtml(card.spec_days || '-')}天</td>
        <td>${status}</td>
        <td>${escapeHtml(card.used_by_chat_title || '')}</td>
        <td>${escapeHtml(card.used_by_user_text || '')}</td>
        <td>${escapeHtml(card.owner_text || '')}</td>
        <td>${escapeHtml(formatTime(card.used_at))}</td>
      </tr>
    `
  }).join('')
}

const renderBatches = (items) => {
  $('batchesBody').innerHTML = items.map((batch) => `
    <tr>
      <td class="code">${escapeHtml(batch.batch_no)}</td>
      <td>${escapeHtml(batch.spec_days)}天</td>
      <td>${escapeHtml(batch.quantity)}</td>
      <td>${escapeHtml(batch.used_count)}</td>
      <td>${escapeHtml(batch.voided_count || 0)}</td>
      <td>${escapeHtml(batch.copy_count)}</td>
      <td>${escapeHtml(batch.export_count)}</td>
      <td>${escapeHtml(formatTime(batch.created_at))}</td>
    </tr>
  `).join('')
}

const formatTime = (value) => {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

const loadKeys = async () => {
  const params = currentFilters()
  const cardsResponse = await api(`/admin/api/keys?${params.toString()}`)
  const batchParams = new URLSearchParams()
  if ($('filterSpec').value) batchParams.set('spec_days', $('filterSpec').value)
  if ($('filterKeyword').value.trim()) batchParams.set('keyword', $('filterKeyword').value.trim())
  const batchesResponse = await api(`/admin/api/key-batches?${batchParams.toString()}`)
  renderCards(cardsResponse.data.items)
  renderBatches(batchesResponse.data.items)
}

const selectedCardIds = () =>
  [...document.querySelectorAll('.card-check:checked')]
    .map((input) => Number(input.value))
    .filter(Boolean)

const loadAnnouncement = async () => {
  const response = await api('/admin/api/announcement')
  const data = response.data
  $('announcementEnabled').checked = Boolean(data.enabled)
  $('announcementEntry').value = data.entry_text || ''
  $('announcementUrl').value = data.target_url || ''
  $('announcementMessage').value = data.message_text || ''
}

const loadPlatformConfig = async () => {
  const response = await api('/admin/api/platform-config')
  const data = response.data
  $('platformName').value = data.platform_name || ''
  $('botDisplayName').value = data.bot_display_name || ''
  $('webAdminTitle').value = data.web_admin_title || ''
  $('maintenanceNotice').value = data.maintenance_notice || ''
  $('contactText').value = data.contact_text || ''
  $('helpText').value = data.help_text || ''
}

const renderAccounts = (items) => {
  $('accountsBody').innerHTML = items.map((account) => {
    const nextStatus = account.status === 'active' ? 'disabled' : 'active'
    const label = account.status === 'active' ? '禁用' : '启用'
    const disabled = account.id === state.currentAdminId && account.status === 'active' ? 'disabled' : ''
    return `
      <tr>
        <td>${escapeHtml(account.id)}</td>
        <td>${escapeHtml(account.username)}</td>
        <td>${escapeHtml(account.display_name || '')}</td>
        <td>${account.status === 'active' ? '启用' : '禁用'}</td>
        <td>${escapeHtml(formatTime(account.last_login_at))}</td>
        <td>
          <button class="account-status-btn ghost" type="button" data-id="${escapeHtml(account.id)}" data-status="${nextStatus}" ${disabled}>${label}</button>
          <button class="account-reset-btn ghost" type="button" data-id="${escapeHtml(account.id)}">重置密码</button>
        </td>
      </tr>
    `
  }).join('')
}

const loadAccounts = async () => {
  const response = await api('/admin/api/accounts')
  renderAccounts(response.data.items || [])
}

const loadAuditLogs = async () => {
  const response = await api('/admin/api/audit-logs?limit=100')
  $('auditBody').innerHTML = (response.data.items || []).map((item) => `
    <tr>
      <td>${escapeHtml(formatTime(item.created_at))}</td>
      <td>${escapeHtml(item.admin_text || item.admin_account_id || '')}</td>
      <td>${escapeHtml(item.action)}</td>
      <td>${escapeHtml([item.target_type, item.target_id].filter(Boolean).join(':'))}</td>
      <td>${escapeHtml(JSON.stringify(item.detail || {}))}</td>
    </tr>
  `).join('')
}

const showAdminPanel = async (admin) => {
  state.currentAdminId = admin.id
  $('currentAdmin').textContent = admin.display_name || admin.username
  show($('loginPanel'), false)
  show($('adminPanel'), true)
  const specs = await api('/admin/api/key-specs')
  state.specs = specs.data.items || []
  state.copyLimit = specs.data.copy_limit || 40
  fillSpecSelects()
  await Promise.all([loadKeys(), loadAnnouncement(), loadPlatformConfig(), loadAccounts(), loadAuditLogs()])
}

const boot = async () => {
  try {
    const me = await api('/admin/api/auth/me')
    await showAdminPanel(me.data)
  } catch {
    show($('loginPanel'), true)
    show($('adminPanel'), false)
  }
}

$('loginForm').addEventListener('submit', async (event) => {
  event.preventDefault()
  try {
    const response = await api('/admin/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({
        username: $('loginUsername').value.trim(),
        password: $('loginPassword').value,
      }),
    })
    toast('登录成功')
    await showAdminPanel(response.data)
  } catch (error) {
    toast(error.message)
  }
})

$('logoutBtn').addEventListener('click', async () => {
  await api('/admin/api/auth/logout', { method: 'POST', body: '{}' })
  window.location.reload()
})

document.querySelectorAll('.tab').forEach((button) => {
  button.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach((item) => item.classList.remove('active'))
    button.classList.add('active')
    show($('tabKeys'), button.dataset.tab === 'keys')
    show($('tabAnnouncement'), button.dataset.tab === 'announcement')
    show($('tabPlatform'), button.dataset.tab === 'platform')
    show($('tabAccounts'), button.dataset.tab === 'accounts')
    show($('tabVerificationTimeouts'), button.dataset.tab === 'verificationTimeouts')
    show($('tabAdDeliveries'), button.dataset.tab === 'adDeliveries')
    show($('tabAudit'), button.dataset.tab === 'audit')
  })
})

$('generateForm').addEventListener('submit', async (event) => {
  event.preventDefault()
  try {
    const response = await api('/admin/api/key-batches', {
      method: 'POST',
      body: JSON.stringify({
        spec_days: Number($('specSelect').value),
        quantity: Number($('quantityInput').value),
      }),
    })
    state.generatedText = response.data.copied_text || ''
    $('generatedText').value = state.generatedText
    const total = response.data.batch.quantity
    const copied = response.data.copied_count
    $('generatedHint').textContent = response.data.truncated
      ? `本次 ${total} 条，已准备最近创建的 ${copied} 条`
      : `本次 ${total} 条可直接复制`
    show($('generateResult'), true)
    await loadKeys()
    toast('卡密批次已生成')
  } catch (error) {
    toast(error.message)
  }
})

$('copyGeneratedBtn').addEventListener('click', async () => {
  try {
    await copyText(state.generatedText || $('generatedText').value)
    toast('已复制本次卡密')
  } catch (error) {
    toast(error.message)
  }
})

$('refreshBtn').addEventListener('click', loadKeys)
$('applyFilterBtn').addEventListener('click', loadKeys)

$('selectAllCards').addEventListener('change', (event) => {
  document.querySelectorAll('.card-check:not(:disabled)').forEach((input) => {
    input.checked = event.target.checked
  })
})

const copySelected = async (withMeta) => {
  const ids = selectedCardIds()
  if (!ids.length) {
    toast('请先选择卡密')
    return
  }
  try {
    const response = await api('/admin/api/keys/copy', {
      method: 'POST',
      body: JSON.stringify({ card_ids: ids, with_meta: withMeta }),
    })
    await copyText(response.data.copied_text)
    toast(`已复制 ${response.data.count} 条卡密`)
    await loadKeys()
  } catch (error) {
    toast(error.message)
  }
}

$('copySelectedBtn').addEventListener('click', () => copySelected(false))
$('copySelectedMetaBtn').addEventListener('click', () => copySelected(true))

$('voidSelectedBtn').addEventListener('click', async () => {
  const ids = selectedCardIds()
  if (!ids.length) {
    toast('请先选择未激活卡密')
    return
  }
  if (!window.confirm(`确认作废选中的 ${ids.length} 条卡密？作废后不可核销。`)) return
  try {
    const response = await api('/admin/api/keys/void', {
      method: 'POST',
      body: JSON.stringify({ card_ids: ids }),
    })
    toast(`已作废 ${response.data.changed} 条卡密`)
    await loadKeys()
  } catch (error) {
    toast(error.message)
  }
})

$('exportBtn').addEventListener('click', () => {
  const params = currentFilters()
  params.delete('limit')
  window.location.href = `/admin/api/keys/export?${params.toString()}`
})

$('announcementForm').addEventListener('submit', async (event) => {
  event.preventDefault()
  try {
    await api('/admin/api/announcement', {
      method: 'PUT',
      body: JSON.stringify({
        enabled: $('announcementEnabled').checked,
        entry_text: $('announcementEntry').value,
        target_url: $('announcementUrl').value,
        message_text: $('announcementMessage').value,
      }),
    })
    toast('公告栏配置已保存')
  } catch (error) {
    toast(error.message)
  }
})

$('platformConfigForm').addEventListener('submit', async (event) => {
  event.preventDefault()
  try {
    await api('/admin/api/platform-config', {
      method: 'PUT',
      body: JSON.stringify({
        platform_name: $('platformName').value,
        bot_display_name: $('botDisplayName').value,
        web_admin_title: $('webAdminTitle').value,
        maintenance_notice: $('maintenanceNotice').value,
        contact_text: $('contactText').value,
        help_text: $('helpText').value,
      }),
    })
    toast('平台公共配置已保存')
  } catch (error) {
    toast(error.message)
  }
})

$('accountForm').addEventListener('submit', async (event) => {
  event.preventDefault()
  try {
    await api('/admin/api/accounts', {
      method: 'POST',
      body: JSON.stringify({
        username: $('accountUsername').value.trim(),
        display_name: $('accountDisplayName').value.trim(),
        password: $('accountPassword').value,
      }),
    })
    $('accountForm').reset()
    toast('后台账号已创建')
    await loadAccounts()
  } catch (error) {
    toast(error.message)
  }
})

$('accountsBody').addEventListener('click', async (event) => {
  const statusButton = event.target.closest('.account-status-btn')
  const resetButton = event.target.closest('.account-reset-btn')
  try {
    if (statusButton) {
      await api(`/admin/api/accounts/${statusButton.dataset.id}/status?status=${statusButton.dataset.status}`, {
        method: 'POST',
        body: '{}',
      })
      toast('账号状态已更新')
      await loadAccounts()
    }
    if (resetButton) {
      const password = window.prompt('请输入新密码，至少 6 位')
      if (!password) return
      await api(`/admin/api/accounts/${resetButton.dataset.id}/password`, {
        method: 'POST',
        body: JSON.stringify({ password }),
      })
      toast('账号密码已重置')
    }
  } catch (error) {
    toast(error.message)
  }
})

$('passwordForm').addEventListener('submit', async (event) => {
  event.preventDefault()
  try {
    await api('/admin/api/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({
        old_password: $('oldPassword').value,
        new_password: $('newPassword').value,
      }),
    })
    $('passwordForm').reset()
    toast('密码已修改')
  } catch (error) {
    toast(error.message)
  }
})

$('refreshAuditBtn').addEventListener('click', loadAuditLogs)

boot()
